# Latency benchmarking

Per-turn latency measurement for the voice pipeline. Used to compare config changes (VAD, TTS model, LLM streaming) and track TTFA (time-to-first-audio) and stage breakdowns.

## Layout

| Path | Purpose |
|------|--------|
| **`scripts/`** | Harness and reporting (versioned) |
| `scripts/run_latency_test.sh` | E2E: start services → replay WAVs from manifest → report. **Only entrypoint for latency runs.** |
| `scripts/latency_report.py` | Reads `turns.jsonl` + `bot_turns.jsonl`, computes P50/P90, writes Markdown (and optional chart). |
| **`test_data/`** | Inputs (versioned) |
| `test_data/manifest.json` | List of utterances; `wav_dir` points to WAV location (e.g. `~/backend/harness/LatencySet_v1/audio`). |
| **`runs/`** | Outputs (gitignored). One subfolder per run. |

Per-run outputs: `turns.jsonl`, `bot_turns.jsonl`, `replay_results.json`, `summary.md`, optional `latency_report.png`, `tts_audio/*.wav`.

## Usage

From repo root. Requires **LiveKit** (localhost:7880) and **Redis** (localhost:6379) running.

```bash
# Full run (default: all utterances in manifest; timestamped run name)
bash latency/scripts/run_latency_test.sh

# Named run, limit to 3 utterances (quick sanity check)
bash latency/scripts/run_latency_test.sh --run-name quick-test --limit 3

# Custom manifest / WAV dir
bash latency/scripts/run_latency_test.sh --run-name my-run \
  --manifest latency/test_data/manifest.json \
  --wav-dir /path/to/wavs

# Write bar chart to run folder
bash latency/scripts/run_latency_test.sh --run-name baseline --chart
```

Results: `latency/runs/<run-name>/`.

**Note:** `test_full_integration.sh` is for starting the backend for e2e/frontend testing only. It does **not** run latency tests or generate latency reports.

## Metrics

- **TTFA (time-to-first-audio):** Publish end → first TTS audio at client. Primary user-perceived metric.
- **E2E:** Publish start → TTS complete.
- **Pipeline stages:** STT, Redis transit, LLM, TTS TTFA, TTS total, Backend TTFU, Bot playback. Server-side from `turns.jsonl` / `bot_turns.jsonl`; harness adds client-side TTFA/E2E from `replay_results.json`.

Reports are in `summary.md` (and stdout). Use `--chart` for a PNG breakdown.

## Dependencies

- **`tools/publish_wav.py`** — Replays WAVs into a LiveKit room, records timings. Called by `run_latency_test.sh`.
- Thinker and Bot write `turns.jsonl` / `bot_turns.jsonl` to `LATENCY_LOG_DIR` (set by the harness to the run folder).

## Extending

- **New utterances:** Edit `test_data/manifest.json` (and add WAVs to the dir referenced by `wav_dir`).
- **New run types:** Use `--run-name` (e.g. `baseline`, `tts_stream_02_25`) and keep runs under `latency/runs/` for comparison.
- **Report only:** `python latency/scripts/latency_report.py --turns latency/runs/<run>/turns.jsonl --bot-turns latency/runs/<run>/bot_turns.jsonl --manifest latency/test_data/manifest.json --markdown latency/runs/<run>/summary.md`

---

## Maintenance (periodic)

- **TTS model (ElevenLabs):** We use `eleven_flash_v2_5` by default (low-latency). Check [ElevenLabs docs](https://elevenlabs.io/docs) for newer models (e.g. turbo/flash variants) and pricing. Override with `ELEVENLABS_MODEL_ID`. Re-run a short latency test after changing.
- **TTS provider:** Current stack is ElevenLabs-only for streaming. If evaluating other providers (e.g. OpenAI Realtime, Deepgram, PlayHT), add a provider under `speech_services/text_to_speech/providers/` and wire a config/env switch; then run latency comparisons with the same manifest.
- **VAD / endpointing:** `END_SPEECH_MS`, `POST_ROLL_MS` (and related env in `livekit_bot.py`) affect when we commit the user turn. Tighter values reduce TTFA but can increase false endpoints. Re-baseline after changes.
- **Manifest and WAVs:** If the harness WAV dir or manifest schema changes, update `test_data/manifest.json` and ensure `tools/publish_wav.py` and `latency_report.py` stay in sync with any new fields (e.g. category, type).

---

## Future improvements (suggestions)

Ideas from past latency plans; implement as needed for further TTFA or UX gains.

1. **Barge-in** — On user speech during TTS: stop playback, cancel TTS generation, flush buffered audio. Critical for natural conversation; no direct TTFA gain.
2. **Stable-partial endpointing** — Commit turn on (silence ≥ 250ms and transcript stable ~200ms) with a long-silence fallback (e.g. 600ms) to reduce reliance on fixed silence only.
3. **Short-turn system prompt** — Encourage 8–15 word responses to shrink first TTS chunk and indirectly improve TTFA.
4. **ElevenLabs WebSocket / input streaming** — If REST chunked streaming is not enough, consider WebSocket input-streaming API for text-in → audio-out; higher complexity, potential extra latency win.
5. **LLM model** — Verify Gemini (or current LLM) is the low-latency option (e.g. Flash); switch by config if a faster model is available.
6. **Connection warmup** — Pre-establish TTS (or LLM) connection before first user turn to shave 100–200ms on first response.
