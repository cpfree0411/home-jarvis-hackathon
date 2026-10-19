# Hardware

## The living-room unit

| Part | Role |
|---|---|
| **Raspberry Pi 5** | Runs the kiosk (Cage Wayland compositor + Chromium), the visual server, the wake-word service and the Gemini Live voice agent |
| **1024×600 HDMI touch display** | The only screen. Every layout in this repository is designed and tested at exactly 1024×600 |
| **ReSpeaker XVF3800 4-mic array (USB)** | Far-field microphone (on-board XMOS DSP: AEC, beamforming) for wake word and conversation; its 3.5 mm AUX output drives an active speaker for Jarvis's voice and chimes |
| **Active speaker** | On the XVF3800 AUX output |

Software on the Pi: `jarvis-wake` (wake word), `jarvis-live` (Gemini Live session, tools, captions), `jarvis-visual-reactions` (HTTP + SSE server and the web front-end in `kiosk/web`).

## The home server

A Linux machine on the home network runs Home Assistant, gallery curation, the calendar authority, both Ask the Three apps and the OTAKU Gallery app. It owns all keys; the Pi never stores provider credentials for the English apps.

## Field notes

- A Pi reboot can leave the XVF3800 enumerated with the wrong USB audio descriptors (capture returns silence). A small udev-triggered guard reboots the chip when that happens.
- The wake word runs on one processed microphone channel at 16 kHz; the conversation uses Gemini Live's own voice-activity detection to decide when you have finished speaking.
- The display process is watched: if Chromium stops listening to the SSE stream, a watchdog reloads it.

## Running without the hardware

You don't need any of this to try the project. `./scripts/run.sh` serves the same front-end to any desktop browser; set the window (or device emulation) to 1024×600 for the true layout. Touch events work with a touchscreen, or use the mouse. Voice is replaced by the stage page's **Simulated** buttons.
