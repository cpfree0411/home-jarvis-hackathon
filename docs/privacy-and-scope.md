# Privacy and scope

Home Jarvis runs in a family home. Its production system knows our calendars, our photos, who is at the door, what music we play and how the house is set up. None of that belongs in a public repository, so this showcase is an **extraction**, not a mirror.

## How this repository was made

- A **new repository with fresh history**. No private repository and none of its Git history was copied or converted.
- The two English apps were copied from their own clean, purpose-built repositories (tracked files only, at the commits deployed to the home server: Ask the Three `5e0f879`, OTAKU Gallery `a5f7792`).
- Kiosk files were copied from the **Pi's deployed visual revision** (`c59e293`), then: visible strings translated to English; real people's identifiers in code and CSS replaced with fictional ones (`alex`, `sam`); a comment naming the device host removed; profiles that need private data left out entirely.
- Nothing in the production system was modified, restarted or redeployed to make this repository.

## Included

| Item | Why it is safe to publish |
|---|---|
| Kiosk front-end code | Our own code; no data, no endpoints, no keys |
| Showcase server, launcher, tests | Written for this repository |
| Ask the Three EN, OTAKU Gallery EN | Built to be public from day one; each has its own audit |
| Gallery art | Original procedural SVGs, CC0 1.0 |
| Wikipedia snapshot excerpts | CC BY-SA 4.0 with attribution (OTAKU app) |
| Fonts | SIL OFL 1.1 with full license texts |
| Screenshots | Fictional calendar, CC0 art, synthetic stories, public research text |

## Deliberately excluded

Family photos and the Drive-backed family gallery · Google Calendar data and OAuth files · Home Assistant configuration and entities · camera feeds and the care-visit recorder · music library, players and history · news briefing sources and reader · weather location data · stock portfolio cards · Telegram bot and chat ids · sticky notes content · the Korean UI and Korean apps · deployment scripts, unit files, SSH topology, addresses, hostnames and logs · the private English-mode bridge · every `.env` and API key.

The weather visual answer was *not* included even though its renderer is ours: its bundled fixture was captured from our real home weather entity and includes our district.

## What the apps send where (when you run them)

| Flow | Destination | Content |
|---|---|---|
| Ask the Three, live | Nebius Token Factory | The story text you typed (or its transcript) and the approved summary |
| Ask the Three, optional seats | OpenAI / Anthropic, if you configure them | The approved summary |
| Ask the Three speech, optional | Google (Gemini Live transcription), if you configure it | Microphone audio while recording; audio is not stored |
| Research Guide | Wikipedia, AniList | Your search query |
| Research Guide, live | Nebius Token Factory | Your query + bounded public source excerpts (never the artwork, favourites or key) |
| Kiosk showcase | nowhere | Sample data stays in memory |

Keys stay in the server processes; the browser never sees them. Ask the Three keeps stories in a local SQLite file under `./.state/ask`; deleting a story hides it but is not secure erasure.

## Checks performed

- `scripts/public_audit.py` over every publishable file and the full Git history: secret shapes, the exact values of provider keys loaded in the shell, private addresses and home paths, an external list of household terms (kept outside the repository), Hangul, forbidden file types, PNG metadata, file size.
- **gitleaks 8.30.1** (official release, checksum-verified) over the working tree and the Git history.
- Each app's own audit (`apps/ask-the-three/scripts/public_audit.py`, `apps/otaku-gallery/scripts/audit_repo.py`).

Results: [verification.md](verification.md).

## Network exposure

All three servers bind to `127.0.0.1` by default and have no user accounts. Don't expose them to the Internet without an authenticated reverse proxy; anyone who can reach them can spend your API credit.
