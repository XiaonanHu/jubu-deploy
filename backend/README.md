# jubu_backend

Backend for Jubu voice conversation: LiveKit-based real-time voice pipeline, KidsChat conversation core, latency benchmarking, and evaluation tooling.

---

## Quick start (E2E)

**Prerequisites:** LiveKit server (port 7880), Redis (port 6379).

- **Simulator / same machine:** run LiveKit with `livekit-server --dev` (binds to localhost only).
- **Physical device (phone on same WiFi):** run LiveKit so it listens on the LAN. From this repo:  
  `livekit-server --config livekit.yaml`  
  (The repo’s `livekit.yaml` binds to `0.0.0.0` and uses dev keys; set `rtc.node_ip` to your machine’s LAN IP. Set `LIVEKIT_API_SECRET` in `.env` to match the secret in `livekit.yaml` — the same value the backend uses to sign tokens.)

```bash
# Start backend (API, Thinker, Bot Manager); runs a quick validation and leaves services running
./test_full_integration.sh
```

Then start the frontend from the other repo (e.g. `npx expo start`) for end-to-end testing.

**Logs:** `tail -f .api.log` · `tail -f .thinker.log` · `tail -f .bot_manager.log` · `tail -f .bots.log`

**Note:** `test_full_integration.sh` starts the backend for e2e/frontend testing only. It does **not** run latency tests (those live in [latency/](latency/)).

**Tests:** `pytest` runs unit/e2e tests. Tests under `jubu_chat/` require the **jubu_datastore** package (`pip install jubu_datastore`). CI runs only `evaluation/data_generation/tests` when jubu_datastore is not installed. For full tests locally, install jubu_datastore then run `pytest`.

**Follow-up suggestions:** Add a one-line "Prerequisites" section in the repo (e.g. `make deps` or a small script) that checks/prints LiveKit and Redis URLs. Optionally document how to run with a device (e.g. `start_for_device.sh`) vs simulator.

---

## Repo map

| Area | What it is |
|------|------------|
| **Entry points** | `livekit_api.py` (FastAPI, port 8001), `jubu_thinker.py`, `bot_manager.py`, `livekit_bot.py` (one per conversation) |
| **Core** | [jubu_chat/](jubu_chat/) — conversation manager, LLM (e.g. Gemini), interactions, configs. Used by the adapter and by the CLI (`python -m jubu_chat.chat_cli`) |
| **Adapter** | [api_server/jubu_adapter.py](api_server/jubu_adapter.py) — bridges LiveKit/voice stack to jubu_chat and STT/TTS. Used by `livekit_api.py` and `jubu_thinker.py`. Other files in `api_server/` are legacy (see [api_server/README.md](api_server/README.md)). |
| **Latency** | [latency/](latency/) — per-turn latency benchmarking (TTFA, stage breakdowns). Entrypoint: `latency/scripts/run_latency_test.sh` |
| **Evaluation** | [evaluation/](evaluation/) — data creation (tagging, filtering, segmentation) and evaluation pipeline (response generation, annotation, rubric grading) |
| **Supporting** | [speech_services/](speech_services/) — STT/TTS providers (Google, OpenAI, ElevenLabs, etc.). [tools/](tools/) — e.g. WAV replay for latency harness. |

**Follow-up suggestions:** Consider moving `jubu_adapter.py` out of `api_server/` into a dedicated module (e.g. root-level `adapters/` or `voice_adapter/`) so the “API server” name doesn’t suggest the old standalone servers; then `api_server/` could be retired or limited to legacy reference. If you keep it in `api_server/`, the current README there now makes the split (adapter vs legacy) explicit.

---

## Key documentation

| Doc | Purpose |
|-----|--------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System overview, components, file layout, API, env, troubleshooting |
| [SYSTEM_FLOW.md](SYSTEM_FLOW.md) | Step-by-step voice pipeline (VAD, STT, Redis, LLM, TTS), latency notes, tuning |
| [latency/README.md](latency/README.md) | Latency runs, metrics, manifest, reporting |
| [jubu_chat/README.md](jubu_chat/README.md) | KidsChat CLI and options |
| [evaluation/README.md](evaluation/README.md) | Evaluation data creation (tagging, filtering, segmentation, selection) |
| [evaluation/evaluation_pipeline/README.md](evaluation/evaluation_pipeline/README.md) | Response generation, annotation, AI rubric grading |
| [api_server/README.md](api_server/README.md) | Adapter role and legacy server reference |

**Follow-up suggestions:** If you add more top-level docs (e.g. STARTUP_GUIDE, DEPLOYMENT), list them here and keep this table as the single “docs index.”

---

## Latency

Per-turn latency (TTFA, E2E, stage breakdowns) is run from [latency/](latency/). Livekit server must be up; then:

```bash
bash latency/scripts/run_latency_test.sh
# Optional: --run-name my-run --limit 3 --chart
```

Results go to `latency/runs/<run-name>/`. See [latency/README.md](latency/README.md) for manifest, metrics, and dependencies (e.g. `tools/publish_wav.py`).

**Follow-up suggestions:** None beyond keeping the manifest and report script in sync if you add new fields (e.g. category, type).

---

## Evaluation

- **Data creation:** Curated segments from CHILDES-style data (tagging → filtering → normalization → segmentation → selection). See [evaluation/README.md](evaluation/README.md).
- **Pipeline:** Generate AI responses, prepare annotation, human/AI rubric grading. See [evaluation/evaluation_pipeline/README.md](evaluation/evaluation_pipeline/README.md).

**Follow-up suggestions:** In the root README you could add one “canonical” example command per phase (e.g. one for data creation, one for pipeline) if you want a single place to copy-paste from.

---

## Supporting pieces

- **speech_services/** — STT/TTS factories and providers; used by the bot, thinker, adapter, and jubu_chat CLI.
- **tools/** — Utilities including `publish_wav.py` (used by the latency harness).
- **utils/** — Placeholder package (currently empty).

The parent app (auth, profiles, conversation list for parents) lives in a separate repo (e.g. `jubu_parent_app`) and has its own backend; it shares the same database via `jubu_datastore` / `jubu_chat` datastores.

**Follow-up suggestions:** If `utils/` stays empty, consider removing it or adding a short note here that it’s reserved for shared helpers.
