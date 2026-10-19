# Server and Home Pi integration contract

This checkout is the complete English application. The Pi/gallery integrator
owns locale switching, routing, iframe launch and deployment. Installing this
package neither changes a different application nor installs a running service.

## Launch and readiness

```sh
.venv/bin/ask-three-en check --env-file .env
.venv/bin/ask-three-en serve --env-file .env --host 127.0.0.1 --port 8794
```

CLI `--host` and `--port` override environment configuration. `--env-file` is
explicit, accepts simple KEY=VALUE lines, and does not override existing env.
It is not a shell interpreter: no command expansion or multiline values.
`python -m ask_three_en.cli` is equivalent to the installed entry point.
Python 3.11+; one process and one independent SQLite database. Do not run
multiple uvicorn workers. SIGTERM gracefully stops the server. Interrupted
organizing stories become FAILED on restart; interrupted panel seats become
FAILED and reveal alongside any completed results.

| Route | Contract |
| --- | --- |
| `GET /` | 200 HTML, `lang="en"`, complete UI; no credentials in HTML |
| `GET /health` | 200 JSON: `ok: true`, `edition: "en"`, `version`, `organizer`, `panel`, `stt` |
| `GET /api/config` | Seat identity and `live` flag, sample stories, speech availability, UI limits |
| `GET /app.js`, `/style.css`, `/fonts/{name}` | Bundled UI assets; all browser asset/API URLs are relative |
| `POST /api/stories` | JSON `source: text|sample|voice`, optional `sample_id`; returns `id` |
| `POST /api/stories/{id}/text` | JSON `text`; starts organization |
| `GET /api/stories/{id}` | DRAFT → ORGANIZING → REVIEW → WAITING → REVEALED; FAILED on organizer fault |
| `POST /api/stories/{id}/approve` | JSON `{}`; snapshots the approved input and starts three independent seats |
| `GET /api/stories/{id}/transcript` | Original text after review, restricted by the same local network policy |
| `GET /api/stories` | Newest revealed stories, seat identities and aggregate |
| `DELETE /api/stories/{id}` | Soft deletion of a revealed story |
| `WS /ws/transcribe/{id}` | Optional: PCM16 LE mono 16 kHz binary chunks; text `stop` ends recording |

Panel GET replies expose **only** `{"status":"WAITING","members":["nemotron","gpt","claude"]}`
until every seat is COMPLETED or FAILED. REVEALED contains each member's
provider/model/live identity, answer or failure, fixed seat order and aggregate.
Three independent calls receive the same approved positions; exactly one seat
sees reversed A/B order, and its choice is mapped back. No answer is passed to
another seat. Strength labels are ordinal, not probabilities or calibrated
confidence. Fixtures are prepared examples, not simulated provider responses.

WebSocket events are JSON `ready`, `interim` / `final_segment` (text),
`complete` (text) or `error` (bounded code). An allowed Origin is required;
one active recording at a time. Raw audio is capped at ten minutes, streamed to
Google, and not saved. Browser secure-context and microphone permission rules
still apply. Speech providers and real microphones are separate runtime checks.

`/health` is local readiness and configuration readback. It creates no model
request and does not assert valid credentials, quota, CLI login or reachability
of upstream providers. A bounded synthetic capability smoke is required after
deployment under the actual service environment.

## Independent runtime configuration

| Variable | Default / role |
| --- | --- |
| `ASK_THREE_HOST`, `ASK_THREE_PORT` | `127.0.0.1`, `8794` |
| `ASK_THREE_STATE` | `$XDG_STATE_HOME/ask-three-en` or `~/.local/state/ask-three-en` |
| `ASK_THREE_DB` | `<state>/stories.sqlite3` |
| `ASK_THREE_ALLOWED_CLIENTS` | `127.0.0.1/32,::1/128`; actual TCP peers, comma-separated IP/CIDR |
| `ASK_THREE_ALLOWED_HOSTS` | `127.0.0.1,localhost,[::1]`; names without ports |
| `ASK_THREE_ALLOWED_ORIGINS` | `http://127.0.0.1:8794,http://localhost:8794`; exact scheme/host/port |
| `ASK_THREE_FRAME_ANCESTORS` | CSP `'self'`; explicitly allow the embedding gallery origin if needed |
| `ASK_THREE_WS_BASE` | Empty; optional full `ws:` / `wss:` URL ending in `/ws/transcribe/`; story id is appended |
| `ASK_THREE_KIOSK_LEASE_URL` | Empty; optional operator-owned microphone lease endpoint |
| `ASK_THREE_ORGANIZER` | `nebius` when key is present, otherwise `fixture` (exact bundled samples only) |
| `ASK_THREE_NEMOTRON_MODEL`, `ASK_THREE_ORGANIZER_MODEL` | `nvidia/Nemotron-3-Ultra-550b-a55b` |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1`; HTTPS only for requests |
| `ASK_THREE_SEAT_NEMOTRON` | `nebius` when key present, else `fixture` |
| `ASK_THREE_SEAT_GPT` | `openai` when key present, else `fixture`; opt-in `codex-cli` |
| `ASK_THREE_SEAT_CLAUDE` | `anthropic` when key present, else `fixture`; opt-in `claude-cli` |
| `ASK_THREE_OPENAI_MODEL`, `OPENAI_BASE_URL` | Explicit model required for API; default base `https://api.openai.com/v1` |
| `ASK_THREE_ANTHROPIC_MODEL`, `ASK_THREE_CLAUDE_MODEL` | `claude-sonnet-5-5`; choose a model your account supports |
| `ASK_THREE_CODEX_MODEL` | Explicit model required for CLI |
| `ASK_THREE_STT`, `ASK_THREE_STT_LANGUAGE` | `gemini-live` when Google key present else `off`; `en-US` or `auto` |
| `ASK_THREE_MAX_INFLIGHT`, `ASK_THREE_DAILY_LIVE_LIMIT` | `2`, `60`; panel daily count uses UTC |

Any seat can explicitly use `fixture`. A configured live seat with a missing
or invalid key fails honestly. Credentials: `NEBIUS_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY` remain in the server environment only.
CLI overrides: `ASK_THREE_CODEX_BIN`, `ASK_THREE_CLAUDE_BIN`,
`ASK_THREE_CODEX_AUTH`, `ASK_THREE_CLAUDE_CREDENTIALS`.
The install never searches another project for secrets or model configuration.

## Proxy and iframe

Prefer a same-origin HTTPS proxy: for example `/ask-en/` forwards to this
server's `/` and strips the prefix, including WebSocket requests. Preserve the
trailing slash on the public index URL so relative assets resolve correctly.
Allow the proxy's actual TCP address in `ASK_THREE_ALLOWED_CLIENTS` and the
public request Host and Origin in their respective allowlists. Forwarded headers
do not override client admission. Do not expose an unauthenticated proxy to the
Internet; the app has no user accounts.

For a cross-origin iframe, explicitly set `ASK_THREE_FRAME_ANCESTORS` to the
gallery's HTTPS origin and give the iframe `allow="microphone"`. The browser
may impose additional Permissions-Policy requirements at the parent origin.
For same-origin embedding the child signals close with
`postMessage({type: 'ask-three-close'}, window.location.origin)`; the parent
must validate `event.origin` and `event.source` before acting. Cross-origin
embedding needs a parent-owned close control; the child only targets its own origin.

The optional microphone lease URL accepts JSON POST with `action` of
`acquire`, `heartbeat` or `release`; acquire must return HTTP 2xx on success
and a non-2xx status on conflict. The response body is not inspected.
The client heartbeats every 30 seconds while leased and releases on exit/page
hide. The operator implements this endpoint; this app does not modify another
service or its microphone owner. Leave it unset for a standalone browser.

## Operator deployment check

Use the example unit only after substituting the install and env paths. Give
the runtime its own state directory and explicit PATH. API seats need only
Python and HTTPS egress; CLI seats additionally need their launcher's complete
interpreter chain, login files and configured model access. The service example
does not assume an interactive login shell or install global tools.

After installing a new build, restart only this English service. Read back its
process/build and `/health`, load `/`, then run the bounded synthetic workflow.
For a fully live test, use `--require-live` with explicit spending authorization.
For speech, verify a real device separately from scripted browser tests. Roll
back to the previous package and state backup if needed; never share another
app's state or port. The source finishing task does not deploy or change the Pi.
