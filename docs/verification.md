# Verification

Everything below was run on 2026-10-20 (KST) on Linux, Python 3.12.3, Node 22.22.2, Chromium via Playwright 1.64.0. "Clean clone" means `git clone` of this repository into an empty directory, with no virtual environment, no `.env` and no provider keys in the shell. Machine-readable results are in [`verification/`](verification/).

## Results

| # | Check | Command | Result |
|---|---|---|---|
| 1 | Install from a clean clone | `./scripts/install.sh` | **PASS** |
| 2 | Offline suite (no keys, no network beyond loopback) | `./scripts/test.sh` | **PASS** — showcase/launcher 21 passed, Ask the Three 31 passed, OTAKU Gallery 86 passed, week-calendar JS suite passed (also under `TZ=America/Los_Angeles`), `node --check` on all kiosk scripts, public audit PASS |
| 3 | Each app's own public audit inside this repo | `apps/ask-the-three/scripts/public_audit.py`; `apps/otaku-gallery/scripts/audit_repo.py --history` | **PASS** (57 candidate files, font hashes OK) / **clean** (93 files) |
| 4 | Demo mode browser walk-through at 1024×600, touch enabled | `./scripts/run.sh --demo` + `python scripts/browser_check.py <url> <dir>` | **PASS** — 18 screens, 14 functional checks, 0 console errors, 0 page errors, 0 horizontal overflow, 0 Hangul ([browser-demo.json](verification/browser-demo.json)) |
| 5 | Ask the Three end-to-end without keys, through the kiosk proxy | `apps/ask-the-three/scripts/smoke_e2e.py http://127.0.0.1:8780/ask-en/` | **PASS** — organizer `prepared-sample`, three fixture seats, `live_votes: 0` ([ask-demo-e2e.json](verification/ask-demo-e2e.json)) |
| 6 | Stage page at 390×844, 768×1024, 1280×800, 1920×1080 | Playwright | **PASS** — no overflow, no console errors |
| 7 | **Live** Ask the Three end-to-end through the kiosk proxy | `./scripts/run.sh` (Nebius key) + `smoke_e2e.py` | **PASS** — organizer `nvidia/Nemotron-3-Ultra-550b-a55b` 2.6 s; panel 2.1 s; Nemotron seat `nebius`, live, COMPLETED; GPT and Claude fixtures; `live_votes: 1`; 0 embargo leaks; 0 Hangul ([ask-live-e2e.json](verification/ask-live-e2e.json)) |
| 8 | **Live** browser walk-through incl. a Nemotron Research Guide page | `browser_check.py` against live mode | **PASS** — page badged *NVIDIA Nemotron 3 Ultra*, citations rendered, keyboard typed `Cyberpunk`, research lease released on close ([browser-live.json](verification/browser-live.json)) |
| 9 | **Live** single judge call | `ask-three-en smoke-nemotron --yes` | **PASS** — model listed by `/v1/models`, served model = requested, 362 + 113 tokens, 1.67 s, ≈ $0.0007 ([ask-nemotron-smoke.json](verification/ask-nemotron-smoke.json)) |
| 10 | **Live** Research Guide writer | `apps/otaku-gallery/scripts/model_smoke.py` | **PASS** — HTTP 200, model validated, strict schema validated, 939 + 934 tokens, 2.84 s, ≈ $0.0037 ([otaku-model-smoke.json](verification/otaku-model-smoke.json)) |
| 11 | Invalid key is reported, not hidden | `NEBIUS_API_KEY=invalid … smoke-nemotron`; `NebiusWriter.write` | **PASS** — Ask: `nebius_models_http_401`; Research: `nebius_http_401` → page status `evidence_only`, "No AI summary was produced…" |
| 12 | Public audit over files **and history** with real key values loaded and an external household-term list | `AUDIT_PRIVATE_TERMS=<file outside repo> python scripts/public_audit.py --history` | **PASS** (see final report for counts) |
| 13 | gitleaks 8.30.1, working tree and Git history | `gitleaks dir .`, `gitleaks git .` | **PASS** — no leaks |
| 14 | Production untouched | process ids/uptime of the home server's English services before/after; no restarts | **PASS** — services kept their original PIDs; tests used ports 18780/18794/18805 |

Rows 7–10 made about seven Nebius requests in total (well under $0.05 at list prices).

## Not verified here

- A physical touch screen and a physical microphone. The browser runs used Chromium touch emulation; voice was simulated. (Real-device results from 2026-10-19 are summarised in [hackathon-updates.md](hackathon-updates.md#6-english-mode-on-the-real-pi--2026-10-19).)
- Live GPT and Claude seats (no keys used for this repository's runs).
- Speech input (`GEMINI_API_KEY`) through the showcase proxy. The WebSocket tunnel itself is unit-tested.
- macOS and Windows. The apps' own docs list what their authors checked.
- Behaviour under load or rate limiting.

## Reproduce

```sh
./scripts/install.sh && ./scripts/test.sh
.venv/bin/python -m pip install -c apps/ask-the-three/constraints.txt playwright
.venv/bin/python -m playwright install chromium
./scripts/run.sh --demo &                       # or with a key for live mode
.venv/bin/python scripts/browser_check.py http://127.0.0.1:8780 ./browser-check
.venv/bin/python apps/ask-the-three/scripts/smoke_e2e.py http://127.0.0.1:8780/ask-en/
```

`browser_check.py` taps one Research Guide topic: free without a key, one Nemotron call with one. `smoke_e2e.py` in live mode makes one organizer and one judge call per live seat.
