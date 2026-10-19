# Release validation · 2026-10-19

The existing gallery was finished in place. This repository is independently installable, has eight bundled CC0 procedural SVGs, uses English UI text, and runs without private services. The initial local commit contains the audited public tree. No remote is configured and nothing has been pushed.

## Results

| Check | Result | Evidence |
| --- | --- | --- |
| Unit / HTTP / model / evidence / English / audit contracts | **86/86** | [unit.json](validation/unit.json) |
| Offline browser smoke | **17/17** | [browser-offline.json](validation/browser-offline.json) |
| No-key browser fallback | **17/17** | [browser-fallback.json](validation/browser-fallback.json) |
| Real model browser smoke, public fixture | **18/18** | [model-proof.json](validation/model-proof.json) |
| Keyboard, favorites, focus, errors, kiosk, responsive research, on-screen touch keyboard | **40/40** | [browser-contract.json](validation/browser-contract.json) |
| Touch keyboard on a real 1024×600 kiosk touchscreen, live sources + real Nemotron | **13/14** — the one miss is a correct ambiguity page for `Cyberpunk` (see note)  | [kiosk-touch-keyboard.json](validation/kiosk-touch-keyboard.json) |
| Fresh wheel installation / isolated execution | **10/10** | [install.json](validation/install.json) |
| Live artist / character / work sources | **3/3** | [live-sources.json](validation/live-sources.json) |
| Actual installed service / live-source capability smoke | **11/11** | [runtime.json](validation/runtime.json) |
| Browser on running service, cached result / source links | **pass**, zero new paid calls | [runtime-browser.json](validation/runtime-browser.json) |
| Source distribution and wheel build | **pass** | [build.json](validation/build.json); wheel contents checked in install smoke |
| Public tree + Git history + actual credential scan | **clean** | [public-audit.json](validation/public-audit.json) |

The original baseline had 83 tests and three failures. The completed suite includes regressions for same-origin enforcement and character evidence with mixed safe/flagged appearances. Rate limiting stays enabled in production; server tests now isolate their application state.

## Provider/model proof and cost

Both real calls used **Nebius Token Factory** at `api.tokenfactory.us-central1.nebius.com`, with response model **`nvidia/Nemotron-3-Ultra-550b-a55b`** checked exactly and strict structured output validated. The endpoint/model/rates are documented in the [official Nebius cookbook](https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/nemotron3-ultra-550b-a55b.md).

| Call | Input tokens | Output tokens | Estimated USD | Outcome |
| --- | ---: | ---: | ---: | --- |
| Small bundled public Wikipedia fixture through browser | 939 | 934 | 0.003741 | Answered; cited source; zero mechanically unmatched passages |
| Installed service using live public sources | 2314 | 1199 | 0.005911 | Answered; six sources; one passage mechanically unmatched and visibly cautioned |
| Total | 3253 | 2133 | **0.009652** | Below the authorized **$0.25** ceiling |

The [budget ledger](validation/model-budget.json) reserves conservative maximum costs before calls; reservations total $0.132469. Estimates use $1/M input and $3/M output, not an invoice. Logs/evidence omit prompts, keys and response bodies. Screenshots show the public answer. Browser regression tests otherwise use a labeled stub or a deliberately absent key.

## Runtime and integration

Demo: **http://127.0.0.1:8805/**. User unit: **`otaku-gallery-en-demo.service`**, a transient local demo, not a boot-persistent installation. Inspect it with `systemctl --user status otaku-gallery-en-demo.service`; stop this demo only with `systemctl --user stop otaku-gallery-en-demo.service`. Environment changes require restarting that unit. Its installed executable, code, static assets and data were compared with the source; health, configured credential and real research were verified under the actual systemd environment and minimal PATH.

The separate listener on **8795** was preserved. Integration belongs to the host integrator; see the [README integration contract](../README.md#integration-contract) for localhost, CSP, relative URLs and path-prefix proxy behavior. No host application or device service was modified.

## Screenshots

- [Gallery, 1024×600](screenshots/01-gallery-1024x600.png)
- [Details and legal provenance](screenshots/02-details-and-tags-1024x600.png)
- [Real Ultra fixture answer](screenshots/live/04-research-result-1024x600.png)
- [No-key source fallback](screenshots/fallback/04-research-result-1024x600.png)
- [Running service: live-source answer](screenshots/runtime/02-research-1024x600.png)
- [Running service: citations and attribution](screenshots/runtime/03-sources-1024x600.png)
- [On-screen touch keyboard, 1024×600](screenshots/07-research-touch-keyboard-1024x600.png)
- [Desktop](screenshots/06-gallery-desktop-1920x1080.png) and [phone](screenshots/06-gallery-phone-390x844.png)

## Public-release audit and limits

The audit scans publishable files, credentials and Git history; `.env`, local media, environments, caches and build output are excluded by Git. The public tree has no personal home paths, private/LAN addresses, credentials, private artwork or private service dependency. Binary assets are limited to reviewed application screenshots; bundled artwork is source SVG. Commit authors use an anonymous example address. LICENSE, NOTICE, complete CC0/CC BY-SA terms, and snapshot revision/author-history links are included.

Citations are a mechanical safeguard, not semantic fact verification. The live result exercised the visible unmatched-passage caveat. Snapshot coverage is limited to gallery themes. Live APIs can fail or rate-limit; fallback is explicit. The all-ages filter is best-effort. The server is a single-user local demo with shared newest-search-wins behavior and no authentication. The demo stays on localhost; remote exposure needs an authenticated proxy. Real browser checks used Chromium; other browser engines were not exercised.

Only execution evidence is claimed. The canonical job and predecessor execution record are unchanged.
