# Demo guide (about 5 minutes)

Start: `./scripts/run.sh` (live, with `NEBIUS_API_KEY` in `.env`) or `./scripts/run.sh --demo`. Open **http://127.0.0.1:8780/**. The kiosk on the left is the real 1024×600 front-end; the panel on the right plays the voice agent's part. Buttons in quotes are things you would *say* on the real device.

## 1. The quiet screen (30 s)
The kiosk shows the OTAKU gallery: original artwork drifting slowly, crossfading every ~14 s. Swipe or use ‹ › to browse. Nothing else is on screen — that is the point.

## 2. A voice turn (30 s)
Press **"What can you do?"**. The gallery app steps aside, a small state pill shows *Listening* then *Thinking*, and the reply appears line by line as a caption *inside* the picture. When it ends, the gallery returns by itself.

## 3. The week, by voice and touch (90 s)
1. **"What's on this week?"** — seven paper slats slide over the art while Jarvis answers. Today is marked.
2. Tap a day to select it (on the Pi, "move it *here*" then refers to that day). Swipe the slats left/right to change week (swipe up closes), or press **Next week** / **Last week**.
3. **"When is Alex's demo?"** — Thursday is highlighted, filtered to Alex.
4. **"Move the demo an hour later"** — Thursday turns into a question: *Change it like this? 3:00 PM → 4:00 PM*. **Tap _Change_ on the kiosk.** Voice can propose; a person confirms. The slat updates after a re-read (sample data, in memory).
5. **Next skin** cycles Riso → Linen → Moonlight → Tape → Ribbon. **Close** folds it away.

## 4. OTAKU Research Guide — Nemotron (60 s)
1. Tap the picture once (controls appear), then **ⓘ** for details. Tags and suggested topics appear.
2. Tap a topic, e.g. *Mecha* or *Slice of life*. Progress steps show the server fetching sources, then Nemotron writing. In live mode a page arrives in a few seconds, badged **NVIDIA Nemotron 3 Ultra**, with numbered citations and a **Sources read by the server** list. In demo mode you get labelled verbatim excerpts instead.
3. Tap the search field: the on-screen keyboard appears. Type, then **Search**.
4. **Close ×** returns to the gallery; while the guide was open the gallery did not advance.

## 5. Ask the Three — Nemotron (90 s)
1. Press **"Ask the three"**. Jarvis answers, then the app opens over the kiosk (on the Pi this is the voice agent's hand-off).
2. **New story → Try a sample → Use this story.** In live mode Nemotron writes the neutral A/B summary; you can read and approve it. (Demo mode uses the sample's prepared summary, labelled *not AI*.)
3. **Ask the three.** Three sealed slips wait until every judge finishes, then all are revealed together.
4. Read the footer: e.g. **"1 live AI vote · 2 demo fixtures (prepared, not live AI)"** — only seats with real credentials count as live. Fixture cards carry a *DEMO FIXTURE* stamp.
5. **Close** (top right) returns to the gallery.

## What to look for
- Every AI result is labelled live or demo, on screen and in the API.
- The screen returns to the gallery after every interaction; there is no app launcher or menu.
- Touch and voice act on the same thing (the selected day, the proposal, the open artwork).
