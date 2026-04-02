#!/usr/bin/env python3
"""
Print backend user-perceived TTFA latency stats for conversations.

Modes:
  (default)  Detailed report for the latest conversation (per-turn table).
  --all      Summary table across ALL logged conversations (stats only).

It expects per-conversation JSONL logs written by jubu_thinker / livekit_bot:
  <log_dir>/<conversation_id>/turns.jsonl
  <log_dir>/<conversation_id>/bot_turns.jsonl

Usage:
  python scripts/get_conversation_latency_stats.py               # latest, detailed
  python scripts/get_conversation_latency_stats.py --verbose      # latest, extra detail
  python scripts/get_conversation_latency_stats.py --all          # all conversations summary
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, quantiles
from typing import Any

# ── Data loading ────────────────────────────────────────────────────


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _list_conversation_dirs(base_dir: Path) -> list[tuple[float, Path]]:
    """Return (mtime, conv_dir) pairs sorted newest-first."""
    if not base_dir.exists():
        return []
    candidates: list[tuple[float, Path]] = []
    for turns_path in base_dir.glob("*/turns.jsonl"):
        try:
            mtime = turns_path.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, turns_path.parent))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


# ── Stats helpers ───────────────────────────────────────────────────


def _percentiles(values: list[float]) -> dict[str, float | None]:
    clean = [v for v in values if v is not None]
    if not clean:
        return {"min": None, "p50": None, "p90": None, "max": None, "n": 0}
    if len(clean) == 1:
        return {
            "min": clean[0],
            "p50": clean[0],
            "p90": clean[0],
            "max": clean[0],
            "n": 1,
        }
    qs = quantiles(clean, n=100)
    return {
        "min": min(clean),
        "p50": median(clean),
        "p90": qs[89],
        "max": max(clean),
        "n": len(clean),
    }


def _fmt(val: float | None, unit: str = "ms") -> str:
    if val is None:
        return "-"
    return f"{val:.0f}{unit}"


def _ts_to_local(epoch: float | None) -> str:
    if not isinstance(epoch, (int, float)):
        return ""
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone().strftime("%H:%M:%S")
    )


def _ts_to_local_short(epoch: float | None) -> str:
    if not isinstance(epoch, (int, float)):
        return ""
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .astimezone()
        .strftime("%m/%d %H:%M")
    )


def _thinker_recv_ts(r: dict[str, Any]) -> float:
    v = r.get("ts_thinker_recv")
    return float(v) if isinstance(v, (int, float)) else 0.0


def truncate(s: str, max_len: int = 120) -> str:
    s = s or ""
    s = s.replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


# ── Per-conversation analysis ───────────────────────────────────────


def _analyze_conversation(conv_dir: Path) -> dict[str, Any] | None:
    """Load and compute metrics for a single conversation directory."""
    records = _load_jsonl(conv_dir / "turns.jsonl")
    if not records:
        return None

    bot_records = _load_jsonl(conv_dir / "bot_turns.jsonl")
    bot_by_turn_id: dict[str, dict[str, Any]] = {}
    for b in bot_records:
        tid = b.get("turn_id")
        if isinstance(tid, str):
            bot_by_turn_id[tid] = b

    records_sorted = sorted(records, key=_thinker_recv_ts)

    ttfa_vals: list[float] = []
    llm_vals: list[float] = []
    tts_vals: list[float] = []
    missing_ttfa = 0

    for r in records_sorted:
        turn_id = r.get("turn_id")
        bot = bot_by_turn_id.get(turn_id, {}) if isinstance(turn_id, str) else {}
        v = bot.get("dur_user_perceived_ttfa_ms")
        if isinstance(v, (int, float)):
            ttfa_vals.append(float(v))
        else:
            missing_ttfa += 1
        llm_ms = r.get("dur_llm_ms")
        if isinstance(llm_ms, (int, float)):
            llm_vals.append(float(llm_ms))
        tts_ms = r.get("dur_tts_total_ms")
        if isinstance(tts_ms, (int, float)):
            tts_vals.append(float(tts_ms))

    first_ts = _thinker_recv_ts(records_sorted[0])
    last_ts = _thinker_recv_ts(records_sorted[-1])

    return {
        "conversation_id": conv_dir.name,
        "conv_dir": conv_dir,
        "records_sorted": records_sorted,
        "bot_by_turn_id": bot_by_turn_id,
        "n_turns": len(records_sorted),
        "missing_ttfa": missing_ttfa,
        "ttfa": _percentiles(ttfa_vals),
        "llm": _percentiles(llm_vals),
        "tts": _percentiles(tts_vals),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "duration_s": (last_ts - first_ts) if first_ts and last_ts else 0,
        "ttfa_vals": ttfa_vals,
        "llm_vals": llm_vals,
        "tts_vals": tts_vals,
    }


# ── Print: single conversation detail ──────────────────────────────

DETAIL_COL = {
    "#": 3,
    "time": 8,
    "ttfa": 7,
    "llm": 7,
    "tts": 7,
    "user_said": 45,
    "bot_said": 55,
}


def _detail_header() -> str:
    h = DETAIL_COL
    return (
        f"{'#':>{h['#']}}  {'time':<{h['time']}}  {'TTFA':>{h['ttfa']}}  "
        f"{'LLM':>{h['llm']}}  {'TTS':>{h['tts']}}  "
        f"{'user said':<{h['user_said']}}  {'bot said':<{h['bot_said']}}"
    )


def _detail_sep() -> str:
    return "  ".join(
        "-" * DETAIL_COL[k]
        for k in ("#", "time", "ttfa", "llm", "tts", "user_said", "bot_said")
    )


def _detail_row(
    idx: int, time_s: str, ttfa_s: str, llm_s: str, tts_s: str, user: str, bot: str
) -> str:
    h = DETAIL_COL
    return (
        f"{idx:>{h['#']}}  {time_s:<{h['time']}}  {ttfa_s:>{h['ttfa']}}  "
        f"{llm_s:>{h['llm']}}  {tts_s:>{h['tts']}}  "
        f"{truncate(user, h['user_said']):<{h['user_said']}}  "
        f"{truncate(bot, h['bot_said']):<{h['bot_said']}}"
    )


def _print_stats_block(data: dict[str, Any]) -> None:
    """Print the summary stats header block for one conversation."""
    ttfa, llm, tts = data["ttfa"], data["llm"], data["tts"]
    print(f"  conversation : {data['conversation_id']}")
    print(f"  turns        : {data['n_turns']} ({data['missing_ttfa']} missing TTFA)")
    if data["first_ts"]:
        print(
            f"  time range   : {_ts_to_local(data['first_ts'])} - {_ts_to_local(data['last_ts'])}  ({data['duration_s']:.0f}s)"
        )
    print()
    print("  Latency breakdown (ms)")
    print("  " + "-" * 40)
    print(f"  {'':14s}  {'min':>6s}  {'P50':>6s}  {'P90':>6s}  {'max':>6s}")
    for label, s in [("TTFA", ttfa), ("  LLM", llm), ("  TTS total", tts)]:
        print(
            f"  {label:14s}  {_fmt(s['min']):>6s}  {_fmt(s['p50']):>6s}  {_fmt(s['p90']):>6s}  {_fmt(s['max']):>6s}"
        )


def _print_single(data: dict[str, Any], verbose: bool, max_turns: int) -> None:
    print()
    print("  Conversation Latency Report")
    print("  " + "=" * 60)
    _print_stats_block(data)
    print()

    records = data["records_sorted"][: max(max_turns, 0)]
    bot_map = data["bot_by_turn_id"]

    print("  Per-turn detail (oldest first)")
    print("  " + _detail_sep())
    print("  " + _detail_header())
    print("  " + _detail_sep())

    for idx, r in enumerate(records, 1):
        turn_id = r.get("turn_id", "")
        bot = bot_map.get(turn_id, {})
        print(
            "  "
            + _detail_row(
                idx,
                (
                    _ts_to_local(r.get("ts_thinker_recv"))
                    if isinstance(r.get("ts_thinker_recv"), (int, float))
                    else ""
                ),
                _fmt(bot.get("dur_user_perceived_ttfa_ms")),
                _fmt(r.get("dur_llm_ms")),
                _fmt(r.get("dur_tts_total_ms")),
                str(r.get("transcription", "")),
                str(r.get("llm_response", "")),
            )
        )
        if verbose:
            anchor = bot.get("ttfa_anchor_name", "-")
            ts_first = bot.get("ts_first_tts_chunk_pushed")
            ts_first_str = (
                f"{ts_first:.3f}" if isinstance(ts_first, (int, float)) else "-"
            )
            print(
                f"  {'':>{DETAIL_COL['#']}}    turn_id={turn_id}  anchor={anchor}  first_chunk_ts={ts_first_str}"
            )

    print("  " + _detail_sep())
    print()


# ── Print: all conversations summary ───────────────────────────────


def _print_all(all_data: list[dict[str, Any]]) -> None:
    if not all_data:
        print("  No conversations found.", file=sys.stderr)
        return

    all_data_sorted = sorted(all_data, key=lambda d: d["first_ts"] or 0)

    print()
    print("  All Conversations – Latency Summary")
    print("  " + "=" * 100)
    print()

    hdr = (
        f"  {'#':>3s}  {'date':12s}  {'conv_id':36s}  {'turns':>5s}  "
        f"{'TTFA P50':>8s}  {'TTFA P90':>8s}  {'LLM P50':>8s}  {'LLM P90':>8s}"
    )
    sep = "  " + "-" * 100
    print(hdr)
    print(sep)

    agg_ttfa: list[float] = []
    agg_llm: list[float] = []
    total_turns = 0

    for idx, d in enumerate(all_data_sorted, 1):
        ts_str = _ts_to_local_short(d["first_ts"]) if d["first_ts"] else "-"
        ttfa, llm = d["ttfa"], d["llm"]
        print(
            f"  {idx:3d}  {ts_str:12s}  {d['conversation_id']:36s}  {d['n_turns']:5d}  "
            f"{_fmt(ttfa['p50']):>8s}  {_fmt(ttfa['p90']):>8s}  "
            f"{_fmt(llm['p50']):>8s}  {_fmt(llm['p90']):>8s}"
        )
        agg_ttfa.extend(d["ttfa_vals"])
        agg_llm.extend(d["llm_vals"])
        total_turns += d["n_turns"]

    print(sep)

    agg_ttfa_stats = _percentiles(agg_ttfa)
    agg_llm_stats = _percentiles(agg_llm)

    print()
    print(f"  Aggregate ({len(all_data_sorted)} conversations, {total_turns} turns)")
    print("  " + "-" * 40)
    print(f"  {'':14s}  {'min':>6s}  {'P50':>6s}  {'P90':>6s}  {'max':>6s}")
    for label, s in [("TTFA", agg_ttfa_stats), ("LLM", agg_llm_stats)]:
        print(
            f"  {label:14s}  {_fmt(s['min']):>6s}  {_fmt(s['p50']):>6s}  {_fmt(s['p90']):>6s}  {_fmt(s['max']):>6s}"
        )
    print()


# ── Entry point ─────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Conversation latency (TTFA) stats.")
    parser.add_argument(
        "--log-dir",
        default=os.getenv(
            "CONVERSATION_LATENCY_LOG_DIR", "logs/latency/conversation_logs"
        ),
        help="Directory containing per-conversation latency subfolders.",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--all",
        "-a",
        action="store_true",
        dest="show_all",
        help="Show a summary table for ALL logged conversations (no per-turn detail).",
    )
    mode.add_argument(
        "--id",
        dest="conversation_id",
        help="Show detailed report for a specific conversation ID.",
    )

    parser.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help="Max turns to display in detail mode.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show extra per-turn detail (anchor, turn_id, timestamps).",
    )
    args = parser.parse_args()

    base_dir = Path(args.log_dir)
    conv_dirs = _list_conversation_dirs(base_dir)
    if not conv_dirs:
        print(f"No structured latency logs found under: {base_dir}", file=sys.stderr)
        sys.exit(1)

    if args.show_all:
        all_data = []
        for _, cdir in conv_dirs:
            d = _analyze_conversation(cdir)
            if d:
                all_data.append(d)
        _print_all(all_data)
        return

    # Single conversation mode (latest or by --id)
    if args.conversation_id:
        target = base_dir / args.conversation_id
        if not target.exists():
            print(f"Conversation not found: {target}", file=sys.stderr)
            sys.exit(1)
    else:
        target = conv_dirs[0][1]  # latest

    data = _analyze_conversation(target)
    if not data:
        print(f"No records in conversation: {target}", file=sys.stderr)
        sys.exit(1)

    _print_single(data, args.verbose, args.max_turns)


if __name__ == "__main__":
    main()
