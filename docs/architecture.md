# Architecture

## The production system (in our home)

```
                         Living room                                         Home server (Linux)
┌──────────────────────────────────────────────────────┐        ┌───────────────────────────────────────────┐
│ Raspberry Pi 5                                       │        │ Home Assistant (devices, calendars)       │
│                                                      │        │ Gallery curation (art, nature, OTAKU, …)  │
│  jarvis-wake ── wake word on the XVF3800 mic         │        │ Calendar authority (read + confirmed edit)│
│       │                                              │        │ Ask the Three (Korean)      :8793         │
│  jarvis-live ── Gemini Live voice session, tools ────┼──HTTP──┤ Ask the Three EN            :8794 ──┐     │
│       │  semantic states, captions, overlay requests │        │ OTAKU Gallery EN            :8805 ──┤     │
│       ▼                                              │        └─────────────────────────────────────┼─────┘
│  jarvis-visual-reactions (Python HTTP + SSE)         │   SSH local forward (Home-owned,            │
│    /api/events  ── SSE to the renderer               │   loopback only) for /ask-en/, /otaku-en/   ▼
│    /api/media, /api/calendar, …  (proxied to Home)   │◄────────────────────────────────── Nebius Token Factory
│    /ask-en/  /otaku-en/  (English mode only)         │                                    NVIDIA Nemotron 3 Ultra
│       ▼                                              │
│  Cage (Wayland kiosk) + Chromium ── 1024×600 touch   │
│    web/index.html: renderer + overlays               │
└──────────────────────────────────────────────────────┘
```

**Division of labour.** The Pi is a *pure renderer* plus the voice loop: it shows what it is told and reports what the user touched. The home server owns data and decisions — which pictures are in the gallery, what the calendar says, whether a calendar change actually happened, and the Ask the Three apps with their keys and databases.

**One channel to the screen.** Everything that changes the screen arrives as a small JSON message on one SSE stream (`/api/events`):

| Message | Meaning |
|---|---|
| `{"type":"state","name":"listening"}` (`thinking`, `searching`, `speaking`, `idle`) | Semantic voice state. The renderer decides how that looks (state pill, wake ripple, dimming). |
| `{"type":"caption","text":"…"}` | Streaming transcript of the spoken reply; shown only while speaking, line by line. |
| `{"type":"calendar","action":"open","view":"week","date":"YYYY-MM-DD"}` | Open/turn the week. `select` + `focus` highlight a day/person/event. |
| `{"type":"calendar","action":"mutation","event":"proposal",…}` | Voice proposed a change; the week shows *Change it like this?* and waits for a **touch** confirmation (`/api/calendar/mutation/confirm`). |
| `{"type":"week_skin","skin":"tape"}` | Voice changed the calendar skin. |
| `{"type":"ask_overlay","action":"open"}` | Voice handed off to Ask the Three; the overlay opens once the reply has finished. |
| `{"type":"visual_answer",…}`, `{"type":"gallery_profile",…}` | Weather/FX/portfolio cards and gallery switching (production only). |

**Touch feeds back into voice.** The week calendar and the gallery report what is on screen (`/api/calendar/context`, `/api/otaku/context`) so "move *this* to Friday" or "tell me about *this* picture" refer to what the person is looking at.

**Overlays share one lease.** `window.jarvisOverlays` arbitrates the screen: the week calendar, Ask the Three, an open Research Guide, and a voice session can't fight over it; a voice wake pre-empts everything.

## The English exhibition mode (Pi, private bridge)

For the hackathon the Pi can switch to English with one command on the home server. In English mode:

- The OTAKU gallery profile shows `/otaku-en/?kiosk=1` (the English app) over the renderer, hidden whenever anything else needs the screen.
- The voice agent's existing Ask hand-off opens `/ask-en/` instead of the Korean app.
- Both paths are served by the Pi's visual server through a Home-owned SSH forward to the home server's loopback ports. The Pi holds no new credentials.

The switch is atomic, verified with a canary and automatically rolled back on failure. The bridge code is private (it encodes household deployment details) and not part of this repository.

## This repository

```
browser ─────────────────────────────► kiosk/showcase.py  (stdlib, :8780)
  /                stage page (kiosk iframe + simulated voice buttons + status)
  /web/…           kiosk/web: the production front-end files
  /api/events      SSE, same message shapes as production
  /api/media       8 CC0 artworks from apps/otaku-gallery
  /api/calendar    fictional household, generated around today; edits in memory
  /api/demo/…      scenarios that emit the voice agent's messages (labelled simulated)
  /ask-en/   ──────► Ask the Three EN   (apps/ask-the-three, uvicorn :8794)  ──► Nebius
  /otaku-en/ ──────► OTAKU Gallery EN   (apps/otaku-gallery, stdlib :8805)   ──► Nebius, Wikipedia, AniList
                    (prefix stripped, Host kept, WebSocket upgrades tunnelled)
```

`scripts/run_showcase.py` starts the three processes with separate state directories under `./.state`, passes the Nebius key only to the two apps, and refuses to start if a port is already taken.

### What the showcase server does *not* do

It implements only the endpoints the included front-end calls. It does not talk to Home Assistant, Google Calendar, a voice model or any household service. Calendar changes are applied to an in-memory copy of the sample week and are lost on restart.
