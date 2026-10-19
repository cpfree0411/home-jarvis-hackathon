# What existed before, and what we built for the hackathon

Home Jarvis is an existing project. This page separates what was already running in our home from what was added for the NVIDIA × Nebius Global AI Hackathon, using dates from the project's Git history and work records.

**Official hackathon start/end dates: Needs verification** (not recorded in our project files). All work listed under *Built for the hackathon* happened on **2026-10-19 and 2026-10-20**, and every NVIDIA Nemotron / Nebius integration in Home Jarvis starts on 2026-10-19 — there is no earlier use of either in any Home Jarvis repository.

## Before the hackathon (not claimed as new)

| Since | Capability | Evidence |
|---|---|---|
| before 2026-09-05 | Pi kiosk runtime (history imported from the device that day) | renderer repo, first commit `98a36c3` |
| 2026-09-05 | Gallery + "Room Light" renderer replacing an earlier character UI | `3bac0ca` |
| 2026-09-06 | Gallery profiles incl. the (Korean) OTAKU feed | `5a27693` |
| by 2026-09-10 | Touch/voice month calendar overlay (redesigned that day) | `05819f3` |
| 2026-09-12 | Wake ripple and semantic state pill (thinking-orbs) | `a04283a` |
| 2026-09-25 | **Ask the Three** (Korean), voice entry from Gemini Live, judges were Gemini / GPT / Claude | ask-the-three `c821525` |
| 2026-10-12 | OTAKU **Research Guide** V2 (Korean), source-grounded, written by a *Gemini-based* agent, with a Korean on-screen keyboard | `7cdb466` |
| 2026-10-14 | Music Explorer (touch) | `3a8d13a` |
| 2026-10-15 / 16 | **Weekly Calendar** visual reaction, then five paper skins | `7c1a736`, skins V2/V3 |
| 2026-10-16 | Ambient sticky notes | `d14753a` |

The kiosk code in `kiosk/web` comes from this pre-existing system. Its English translation and sample-data server are new (below); the renderer, week calendar and overlay logic themselves are not.

## Built for the hackathon (2026-10-19 → 2026-10-20)

### 1. Choosing a Nemotron model on Nebius — 2026-10-19
Real API trials before any integration, with fixed public inputs and spending caps:

- **Nemotron 3.5 Super VL** — vision smoke with three synthetic images: 3/3 HTTP 200, 2.1–3.6 s. Not adopted (we chose text-only grounding).
- **Nemotron 3 Nano 30B, Nemotron 3.5 Lightning** — Korean source-grounded guide: Nano truncated 2/3, Lightning produced valid JSON but unsupported facts. Rejected.
- **Nemotron 3 Super 120B vs Nemotron 3 Ultra 550B** — 5 identical cases each, strict JSON, thinking off: 10/10 valid; median round trip 4.28 s vs 3.94 s; Ultra judged better. **Ultra adopted** (for a demo that shows its sources, not as unreviewed factual output).

### 2. Nemotron joins the household's Ask the Three — 2026-10-19
The Korean production app's Gemini judge seat was replaced by **`nvidia/Nemotron-3-Ultra-550b-a55b`** (strict JSON, thinking off, exact-model check), alongside a full paper-desk UI redesign. Deployed to the home server and verified with a real synthetic panel. (ask-the-three `15c39a0`, `671a845`; not in this public repo — it is the private Korean app.)

### 3. Ask the Three — English edition — 2026-10-19
A new standalone app (`apps/ask-the-three`, origin commit `5e0f879`): English UI and samples, **Nemotron as organizer and judge**, optional GPT/Claude seats that are otherwise *labelled demo fixtures*, English speech input via Gemini Live transcription, keyless demo mode, public-safety audit, 31 tests.

### 4. OTAKU Gallery — English edition with the Nemotron Research Guide — 2026-10-19
A new standalone app (`apps/otaku-gallery`, origin `c7f27b4`): eight original CC0 artworks, English UI, **Nemotron 3 Ultra writing cited research pages** from Wikipedia/AniList evidence with mechanical citation checks, honest excerpt fallback, no runtime dependencies, 86 tests. The Korean guide's Research flow had used a Gemini-based writer; this one uses Nemotron.

### 5. Touch keyboard ported to the English guide — 2026-10-19
The Korean guide's on-screen keyboard (from 2026-10-12) was re-implemented for the English app as a QWERTY/symbols keyboard (`a5f7792`, 22:50 KST). Verified in this repository by touch: tapping ⇧ C Y B E R P U N K types `Cyberpunk`.

### 6. English mode on the real Pi — 2026-10-19
A private, reversible bridge lets the living-room Pi switch between the Korean household UI and an English exhibition mode (`1463d8d`, `a478f20`, `71673d9`; deployed visual revision `c59e293`). In English mode the OTAKU profile shows the English gallery, and the voice agent's existing "open Ask the Three" hand-off opens the English Ask the Three. Real-device acceptance: **23/23** checks, including a synthetic 9-second English voice clip transcribed through the Pi's WebSocket proxy, organized by Nemotron, with **Nemotron and GPT voting live and Claude a disclosed fixture** ("2 live AI votes · 1 demo fixture"). A physical room-microphone test was **not** performed. The bridge itself stays private (it contains household deployment details).

### 7. This public showcase — 2026-10-20
- Extracted the Pi's deployed kiosk front-end (renderer, captions, state pill, wake ripple, week calendar + 5 skins, Ask overlay, OTAKU host), translated its visible strings to English and replaced household identifiers.
- New `kiosk/showcase.py`: the production HTTP/SSE contract with fictional calendar data, in-memory voice-proposed edits confirmed by touch, simulated voice-agent scenarios, and a same-origin proxy (HTTP + WebSocket) to both apps — the same topology as the Pi.
- One-command install/run with Live and Demo modes, port preflight, and per-app state isolation.
- Tests: showcase/launcher (20), ported week-calendar suite, browser walk-through, public audit + gitleaks. Fixed the Ask smoke script to send a real Origin behind a path-prefix proxy.
- Re-verified both Nemotron paths live from this repository (see [verification](verification.md)).

## Not done during the hackathon

- No new voice agent work; the voice agent is simulated in this repository.
- The Korean OTAKU guide's opt-in Nemotron adapter (prototype, 2026-10-19) was **not** deployed to the household.
- No physical microphone acceptance of the English flow.
