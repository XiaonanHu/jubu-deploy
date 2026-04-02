#!/usr/bin/env python3
"""
Latency report script for the Jubu backend pipeline.

Reads turns.jsonl (thinker-side) and optionally bot_turns.jsonl (bot-side),
joins on turn_id, computes P50/P90 for each pipeline stage, and prints
an ASCII breakdown table.

Usage:
    python latency/scripts/latency_report.py \\
        [--turns latency/runs/<run>/turns.jsonl] \\
        [--bot-turns latency/runs/<run>/bot_turns.jsonl] \\
        [--harness-results latency/runs/<run>/replay_results.json] \\
        [--manifest latency/test_data/manifest.json] \\
        [--markdown latency/runs/<run>/summary.md] \\
        [--chart] [--chart-output path]
"""

import argparse
import json
import sys
from pathlib import Path
from statistics import median, quantiles

# ---- Helpers ---------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def p50_p90(values: list[float]) -> tuple[float | None, float | None]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None, None
    if len(clean) == 1:
        return clean[0], clean[0]
    qs = quantiles(clean, n=100)
    return median(clean), qs[89]  # qs[89] = 90th percentile


def fmt(val: float | None, unit: str = "ms") -> str:
    if val is None:
        return "  n/a "
    return f"{val:7.0f}{unit}"


def bar(val: float | None, scale_ms: float = 5000.0, width: int = 30) -> str:
    """ASCII bar proportional to val relative to scale_ms."""
    if val is None:
        return " " * width
    filled = min(int(round(val / scale_ms * width)), width)
    return "█" * filled + "░" * (width - filled)


# ---- Merge helpers ---------------------------------------------------------


def merge_harness_results(turns: list[dict], harness_path: Path) -> list[dict]:
    """
    Enrich turns.jsonl entries with category/type/file from harness results,
    joined on turn_id (JSONL) or by sequential order (JSON with utterances key).
    """
    if not harness_path or not harness_path.exists():
        return turns

    raw = harness_path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None

    harness: list[dict] = []
    if isinstance(data, dict) and "utterances" in data:
        harness = data["utterances"]
    elif isinstance(data, list):
        harness = data
    else:
        harness = load_jsonl(harness_path)

    harness_by_tid = {r["turn_id"]: r for r in harness if "turn_id" in r}
    harness_by_file: dict[str, list[tuple[int, dict]]] = {}
    for idx, rec in enumerate(harness):
        f = rec.get("file")
        if f:
            harness_by_file.setdefault(f, []).append((idx, rec))
    used_harness_idx: set[int] = set()

    enriched = []
    for idx, t in enumerate(turns):
        hr = harness_by_tid.get(t.get("turn_id", ""), {})
        # Fallback 1: file-aware matching (prevents misalignment when some turns timeout)
        if not hr and t.get("file"):
            for h_idx, cand in harness_by_file.get(t["file"], []):
                if h_idx not in used_harness_idx:
                    hr = cand
                    used_harness_idx.add(h_idx)
                    break
        # Fallback 2: positional matching as last resort
        if not hr and idx < len(harness):
            hr = harness[idx]
            used_harness_idx.add(idx)
        merged = dict(t)
        for field in (
            "category",
            "type",
            "file",
            "ttfa_ms",
            "e2e_latency_ms",
            "total_ms",
            "tts_start_ts",
            "tts_first_audio_ts",
            "tts_complete_ts",
            "status",
            "measurement_status",
        ):
            if field in hr and field not in merged:
                merged[field] = hr[field]
        enriched.append(merged)
    return enriched


def load_harness_utterances(harness_path: Path) -> list[dict]:
    """Load replay utterances from replay_results.json (or JSONL fallback)."""
    if not harness_path.exists():
        return []
    raw = harness_path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and "utterances" in data:
        return list(data["utterances"])
    if isinstance(data, list):
        return list(data)
    return load_jsonl(harness_path)


def validate_benchmark_harness(harness_utterances: list[dict]) -> bool:
    """
    Strict benchmark validation:
      - no timeout turns
      - no missing TTFA on successful turns
      - no negative TTFA
    Returns True on pass, False on failure.
    """
    failed = [u for u in harness_utterances if u.get("status") != "ok"]
    missing_ttfa = [
        u
        for u in harness_utterances
        if u.get("status") == "ok" and u.get("ttfa_ms") is None
    ]
    negative_ttfa = [
        u
        for u in harness_utterances
        if isinstance(u.get("ttfa_ms"), (int, float)) and float(u["ttfa_ms"]) < 0
    ]

    if not failed and not missing_ttfa and not negative_ttfa:
        print("Benchmark validation: PASS")
        return True

    print("Benchmark validation: FAIL")
    if failed:
        print(f"  - failed turns: {len(failed)}")
        print("    files:", ", ".join(str(u.get("file", "?")) for u in failed[:8]))
    if missing_ttfa:
        print(f"  - missing TTFA: {len(missing_ttfa)}")
        print(
            "    files:", ", ".join(str(u.get("file", "?")) for u in missing_ttfa[:8])
        )
    if negative_ttfa:
        print(f"  - negative TTFA: {len(negative_ttfa)}")
        print(
            "    files:",
            ", ".join(
                f"{u.get('file','?')}({u.get('ttfa_ms')})" for u in negative_ttfa[:8]
            ),
        )
    return False


def merge_manifest(turns: list[dict], manifest_path: Path) -> list[dict]:
    """
    Enrich turns with category/type/file from the manifest by sequential order.
    Works when turns are produced in the same order as manifest utterances.
    """
    if not manifest_path or not manifest_path.exists():
        return turns
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    utterances = manifest.get("utterances", [])
    enriched = []
    for idx, t in enumerate(turns):
        merged = dict(t)
        if idx < len(utterances):
            utt = utterances[idx]
            for field in ("category", "type", "file"):
                if field in utt and field not in merged:
                    merged[field] = utt[field]
        enriched.append(merged)
    return enriched


def _join_turns(turns: list[dict], bot_turns: list[dict]) -> list[dict]:
    bot_by_id = {r["turn_id"]: r for r in bot_turns if "turn_id" in r}
    joined = []
    for t in turns:
        tid = t.get("turn_id")
        bot = bot_by_id.get(tid, {}) if tid else {}
        joined.append({**t, **{f"bot_{k}": v for k, v in bot.items()}})
    return joined


# ---- Report ----------------------------------------------------------------


def build_report(
    turns: list[dict],
    bot_turns: list[dict],
    outlier_factor: float,
) -> None:
    joined = _join_turns(turns, bot_turns)

    n = len(joined)
    if n == 0:
        print(
            "No turn data found. Run the latency test first (latency/scripts/run_latency_test.sh)."
        )
        return

    # --- Collect per-stage durations ---
    stages = [
        # Server-side breakdown (from turns.jsonl / bot_turns.jsonl)
        ("STT", "dur_stt_ms"),
        ("Redis transit", "dur_redis_ms"),
        ("LLM", "dur_llm_ms"),
        ("TTS TTFA", "dur_tts_ttfa_ms"),
        ("TTS total", "dur_tts_total_ms"),
        ("Backend TTFU", "dur_backend_ttfu_ms"),
        ("Bot playback", "bot_dur_tts_playback_ms"),
        # Client-side harness measurements (from replay_results.json)
        ("Harness TTFA", "ttfa_ms"),
        ("Harness E2E", "e2e_latency_ms"),
    ]

    stage_values: dict[str, list[float]] = {label: [] for label, _ in stages}
    for row in joined:
        for label, key in stages:
            v = row.get(key)
            if v is not None:
                stage_values[label].append(float(v))

    # --- Compute max median for bar scaling ---
    medians = {
        label: median(vals) if vals else 0.0 for label, vals in stage_values.items()
    }
    scale = max(medians.values(), default=1000.0) * 1.2 or 1000.0

    print()
    print("=" * 75)
    print(f"  Jubu Backend Latency Report  (N={n} turns)")
    print("=" * 75)
    print()
    print(
        f"  {'Stage':<18}  {'P50 (ms)':>9}  {'P90 (ms)':>9}  {'Count':>5}  {'Distribution':}"
    )
    print(f"  {'-'*18}  {'-'*9}  {'-'*9}  {'-'*5}  {'-'*30}")

    for label, _ in stages:
        vals = stage_values[label]
        p50, p90 = p50_p90(vals)
        b = bar(p50, scale_ms=scale)
        print(
            f"  {label:<18}  {fmt(p50, ''):>9}  {fmt(p90, ''):>9}  {len(vals):>5}  {b}"
        )

    # --- Harness TTFA summary (prominent, client-perceived metric) ---
    harness_ttfa_vals = stage_values["Harness TTFA"]
    harness_e2e_vals = stage_values["Harness E2E"]
    if harness_ttfa_vals:
        p50_ttfa, p90_ttfa = p50_p90(harness_ttfa_vals)
        p50_e2e, p90_e2e = (
            p50_p90(harness_e2e_vals) if harness_e2e_vals else (None, None)
        )
        print()
        print(f"  ── Harness client-perceived latency (N={len(harness_ttfa_vals)}) ──")
        print(f"  TTFA  P50={fmt(p50_ttfa)}  P90={fmt(p90_ttfa)}")
        if p50_e2e is not None:
            print(f"  E2E   P50={fmt(p50_e2e)}  P90={fmt(p90_e2e)}")

    # --- Per-category breakdown (if category field present) ---
    categories = sorted({r.get("category", "") for r in joined} - {""})
    if categories:
        print()
        print(
            f"  {'Category':<10}  {'N':>4}  {'P50 TTFA':>10}  {'P90 TTFA':>10}  {'P50 backend_ttfu':>18}  {'P90 backend_ttfu':>18}"
        )
        print(f"  {'-'*10}  {'-'*4}  {'-'*10}  {'-'*10}  {'-'*18}  {'-'*18}")
        for cat in categories:
            cat_rows = [r for r in joined if r.get("category") == cat]
            ttfa_v = [
                float(r["ttfa_ms"]) for r in cat_rows if r.get("ttfa_ms") is not None
            ]
            ttfu_v = [
                float(r["dur_backend_ttfu_ms"])
                for r in cat_rows
                if r.get("dur_backend_ttfu_ms") is not None
            ]
            p50_ttfa_c, p90_ttfa_c = p50_p90(ttfa_v)
            p50_ttfu_c, p90_ttfu_c = p50_p90(ttfu_v)
            print(
                f"  {cat:<10}  {len(cat_rows):>4}  "
                f"{fmt(p50_ttfa_c, ''):>10}  {fmt(p90_ttfa_c, ''):>10}  "
                f"{fmt(p50_ttfu_c):>18}  {fmt(p90_ttfu_c):>18}"
            )

    # --- Outlier detection ---
    ttfu_vals = stage_values["Backend TTFU"]
    if ttfu_vals and len(ttfu_vals) >= 3:
        med = median(ttfu_vals)
        threshold = med * outlier_factor
        outliers = [
            r
            for r in joined
            if r.get("dur_backend_ttfu_ms") is not None
            and float(r["dur_backend_ttfu_ms"]) > threshold
        ]
        if outliers:
            print()
            print(
                f"  Outlier turns (backend_ttfu > {outlier_factor:.1f}× median = {threshold:.0f}ms):"
            )
            for r in outliers[:10]:
                print(
                    f"    turn_id={r.get('turn_id','?')[:8]}  "
                    f"ttfu={r.get('dur_backend_ttfu_ms'):.0f}ms  "
                    f"llm={r.get('dur_llm_ms', '?')}ms  "
                    f"tts_ttfa={r.get('dur_tts_ttfa_ms', '?')}ms  "
                    f"text='{str(r.get('transcription',''))[:40]}'"
                )

    print()
    print("=" * 75)
    print()


def build_markdown_report(
    turns: list[dict],
    bot_turns: list[dict],
    outlier_factor: float,
    output_path: Path,
    harness_utterances: list[dict] | None = None,
) -> None:
    """Write a Markdown summary to output_path."""
    joined = _join_turns(turns, bot_turns)
    n = len(joined)

    lines: list[str] = []
    lines.append(f"# Jubu Backend Latency Report")
    lines.append(f"")

    # --- Benchmark issues banner -------------------------------------------
    if harness_utterances:
        skipped = [
            u for u in harness_utterances if u.get("status") == "skipped_too_quiet"
        ]
        timeouts = [u for u in harness_utterances if u.get("status") == "timeout"]
        missing_fa = [
            u
            for u in harness_utterances
            if u.get("status") == "ok"
            and u.get("measurement_status") == "missing_first_audio"
        ]
        neg_ttfa = [
            u
            for u in harness_utterances
            if u.get("status") == "ok"
            and u.get("measurement_status") == "negative_ttfa"
        ]
        hard = skipped + timeouts + missing_fa
        if hard or neg_ttfa:
            lines.append(
                "> **Benchmark issues detected** — metrics below may be incomplete."
            )
            lines.append(">")
            if timeouts:
                lines.append(
                    f"> - **{len(timeouts)} timeout(s):** "
                    + ", ".join(u.get("file", "?") for u in timeouts)
                )
            if skipped:
                lines.append(
                    f"> - **{len(skipped)} skipped (too quiet):** "
                    + ", ".join(u.get("file", "?") for u in skipped)
                )
            if missing_fa:
                lines.append(
                    f"> - **{len(missing_fa)} missing first-audio:** "
                    + ", ".join(u.get("file", "?") for u in missing_fa)
                )
            if neg_ttfa:
                lines.append(
                    f"> - **{len(neg_ttfa)} negative TTFA (measurement only, not a hard failure):** "
                    + ", ".join(u.get("file", "?") for u in neg_ttfa)
                )
            lines.append("")
    lines.append(f"**Turns analysed:** {n}")
    lines.append(f"")

    stages = [
        # Server-side breakdown (from turns.jsonl / bot_turns.jsonl)
        ("STT", "dur_stt_ms"),
        ("Redis transit", "dur_redis_ms"),
        ("LLM", "dur_llm_ms"),
        ("TTS TTFA", "dur_tts_ttfa_ms"),
        ("TTS total", "dur_tts_total_ms"),
        ("Backend TTFU", "dur_backend_ttfu_ms"),
        ("Bot playback", "bot_dur_tts_playback_ms"),
        # Client-side harness measurements (from replay_results.json)
        ("Harness TTFA", "ttfa_ms"),
        ("Harness E2E", "e2e_latency_ms"),
    ]

    stage_values: dict[str, list[float]] = {label: [] for label, _ in stages}
    for row in joined:
        for label, key in stages:
            v = row.get(key)
            if v is not None:
                stage_values[label].append(float(v))

    def ms(v: float | None) -> str:
        return f"{v:.0f} ms" if v is not None else "n/a"

    # Harness TTFA summary at the top of the markdown report
    harness_ttfa_vals = stage_values["Harness TTFA"]
    harness_e2e_vals = stage_values["Harness E2E"]
    if harness_ttfa_vals:
        p50_ttfa, p90_ttfa = p50_p90(harness_ttfa_vals)
        p50_e2e, p90_e2e = (
            p50_p90(harness_e2e_vals) if harness_e2e_vals else (None, None)
        )
        lines.append("## Harness Client-Perceived Latency")
        lines.append("")
        lines.append("| Metric | P50 | P90 | N |")
        lines.append("|---|---|---|---|")
        lines.append(
            f"| TTFA (publish_end → first audio) | {ms(p50_ttfa)} | {ms(p90_ttfa)} | {len(harness_ttfa_vals)} |"
        )
        if p50_e2e is not None:
            lines.append(
                f"| E2E (publish_start → TTS complete) | {ms(p50_e2e)} | {ms(p90_e2e)} | {len(harness_e2e_vals)} |"
            )
        lines.append("")

    lines.append("## Pipeline Stage Breakdown")
    lines.append("")
    lines.append("| Stage | P50 | P90 | N |")
    lines.append("|---|---|---|---|")
    for label, _ in stages:
        vals = stage_values[label]
        p50, p90 = p50_p90(vals)
        lines.append(f"| {label} | {ms(p50)} | {ms(p90)} | {len(vals)} |")
    lines.append("")

    # Per-category breakdown
    categories = sorted({r.get("category", "") for r in joined} - {""})
    if categories:
        lines.append("## By Category (TTFA + Backend TTFU)")
        lines.append("")
        lines.append("| Category | N | P50 TTFA | P90 TTFA | P50 TTFU | P90 TTFU |")
        lines.append("|---|---|---|---|---|---|")
        for cat in categories:
            cat_rows = [r for r in joined if r.get("category") == cat]
            ttfa_v = [
                float(r["ttfa_ms"]) for r in cat_rows if r.get("ttfa_ms") is not None
            ]
            ttfu_v = [
                float(r["dur_backend_ttfu_ms"])
                for r in cat_rows
                if r.get("dur_backend_ttfu_ms") is not None
            ]
            p50_ttfa_c, p90_ttfa_c = p50_p90(ttfa_v)
            p50_ttfu_c, p90_ttfu_c = p50_p90(ttfu_v)
            lines.append(
                f"| {cat} | {len(cat_rows)} "
                f"| {ms(p50_ttfa_c)} | {ms(p90_ttfa_c)} "
                f"| {ms(p50_ttfu_c)} | {ms(p90_ttfu_c)} |"
            )
        lines.append("")

    # Outliers
    ttfu_vals = stage_values["Backend TTFU"]
    if ttfu_vals and len(ttfu_vals) >= 3:
        from statistics import median as _median

        med = _median(ttfu_vals)
        threshold = med * outlier_factor
        outliers = [
            r
            for r in joined
            if r.get("dur_backend_ttfu_ms") is not None
            and float(r["dur_backend_ttfu_ms"]) > threshold
        ]
        if outliers:
            lines.append(
                f"## Outliers (backend_ttfu > {outlier_factor:.1f}× median = {threshold:.0f} ms)"
            )
            lines.append("")
            lines.append("| turn_id | TTFU ms | LLM ms | TTS TTFA ms | Transcript |")
            lines.append("|---|---|---|---|---|")
            for r in outliers[:10]:
                lines.append(
                    f"| {str(r.get('turn_id',''))[:8]} "
                    f"| {r.get('dur_backend_ttfu_ms', 'n/a')} "
                    f"| {r.get('dur_llm_ms', 'n/a')} "
                    f"| {r.get('dur_tts_ttfa_ms', 'n/a')} "
                    f"| {str(r.get('transcription', ''))[:50]} |"
                )
            lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Markdown report written to {output_path}")


def save_chart(turns: list[dict], bot_turns: list[dict], output_path: Path) -> None:
    """Save a horizontal stacked bar chart of median stage durations."""
    try:
        import matplotlib.patches as mpatches
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping chart. pip install matplotlib")
        return

    bot_by_id = {r["turn_id"]: r for r in bot_turns if "turn_id" in r}
    joined = [
        {
            **t,
            **{
                f"bot_{k}": v
                for k, v in bot_by_id.get(t.get("turn_id", ""), {}).items()
            },
        }
        for t in turns
    ]

    stage_defs = [
        ("STT", "dur_stt_ms", "#4C9BE8"),
        ("Redis", "dur_redis_ms", "#A8D5A2"),
        ("LLM", "dur_llm_ms", "#F4A261"),
        ("TTS TTFA", "dur_tts_ttfa_ms", "#E76F51"),
        ("TTS total", "dur_tts_total_ms", "#D62828"),
        ("Bot playback", "bot_dur_tts_playback_ms", "#9B2226"),
    ]

    labels = [s[0] for s in stage_defs]
    medians_ms = []
    for _, key, _ in stage_defs:
        vals = [float(r[key]) for r in joined if r.get(key) is not None]
        medians_ms.append(median(vals) if vals else 0.0)

    colors = [s[2] for s in stage_defs]

    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.barh(labels, medians_ms, color=colors, edgecolor="white")
    ax.bar_label(bars, fmt="%.0f ms", padding=4, fontsize=9)
    ax.set_xlabel("Median duration (ms)")
    ax.set_title(f"Jubu Backend Latency — Median per Stage  (N={len(joined)} turns)")
    ax.invert_yaxis()
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    print(f"Chart saved to {output_path}")


# ---- Main ------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Jubu latency report from JSONL logs")
    parser.add_argument(
        "--turns",
        default="latency/runs/turns.jsonl",
        help="Path to thinker-side JSONL (default: latency/runs/turns.jsonl)",
    )
    parser.add_argument(
        "--bot-turns",
        default="latency/runs/bot_turns.jsonl",
        help="Path to bot-side JSONL (default: latency/runs/bot_turns.jsonl)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to utterance manifest JSON (adds category/type info by sequential order)",
    )
    parser.add_argument(
        "--harness-results",
        default=None,
        help="Path to replay_results.json from publish_wav.py (adds category info)",
    )
    parser.add_argument(
        "--markdown",
        default=None,
        metavar="PATH",
        help="Write a Markdown summary to PATH instead of (or in addition to) stdout ASCII",
    )
    parser.add_argument(
        "--chart",
        action="store_true",
        help="Save a bar chart to latency_report.png",
    )
    parser.add_argument(
        "--chart-output",
        default="latency_report.png",
        help="Chart output path (default: latency_report.png)",
    )
    parser.add_argument(
        "--outlier-factor",
        type=float,
        default=2.0,
        help="Flag turns where backend_ttfu > factor × median (default: 2.0)",
    )
    parser.add_argument(
        "--benchmark-validate",
        action="store_true",
        help="Fail if harness has timeout/missing TTFA/negative TTFA",
    )
    args = parser.parse_args()

    turns_path = Path(args.turns)
    bot_turns_path = Path(args.bot_turns)

    turns = load_jsonl(turns_path)
    bot_turns = load_jsonl(bot_turns_path)

    if not turns and not bot_turns:
        print(f"No data found in {turns_path} or {bot_turns_path}.")
        print("Run a latency test first (latency/scripts/run_latency_test.sh).")
        sys.exit(0)

    harness_utterances: list[dict] = []
    # Enrich turns with category/file from manifest or harness results
    if args.manifest:
        turns = merge_manifest(turns, Path(args.manifest))
    if args.harness_results:
        harness_path = Path(args.harness_results)
        turns = merge_harness_results(turns, harness_path)
        harness_utterances = load_harness_utterances(harness_path)

    # Always print ASCII table to stdout
    build_report(turns, bot_turns, args.outlier_factor)

    # Optionally write Markdown summary
    if args.markdown:
        build_markdown_report(
            turns,
            bot_turns,
            args.outlier_factor,
            Path(args.markdown),
            harness_utterances=harness_utterances,
        )

    if args.chart:
        save_chart(turns, bot_turns, Path(args.chart_output))

    if args.benchmark_validate:
        ok = validate_benchmark_harness(harness_utterances)
        if not ok:
            sys.exit(2)


if __name__ == "__main__":
    main()
