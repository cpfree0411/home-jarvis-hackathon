# NVIDIA Nemotron on Nebius Token Factory

Both Home Jarvis capabilities use the same model through the same API style, independently implemented in each app.

| | Value | Source |
|---|---|---|
| Provider | Nebius Token Factory, OpenAI-compatible Chat Completions | both apps |
| Model | `nvidia/Nemotron-3-Ultra-550b-a55b` (NVIDIA Nemotron 3 Ultra, 550B total / 55B active MoE) | `ask_three_en/config.py`, `otaku_gallery/nebius.py:18` |
| Ask the Three endpoint | `https://api.tokenfactory.nebius.com/v1/chat/completions` (override: `NEBIUS_BASE_URL`) | `ask_three_en/config.py` |
| Research Guide endpoint | `https://api.tokenfactory.us-central1.nebius.com/v1/chat/completions` (fixed) | `otaku_gallery/nebius.py:19` |
| Auth | `Authorization: Bearer $NEBIUS_API_KEY`, read server-side only | both |
| Sampling | `temperature: 0`, `chat_template_kwargs: {"enable_thinking": false}` | both |
| Output | `response_format: {"type": "json_schema", "json_schema": {..., "strict": true}}` | both |
| Tools / streaming | none / non-streaming | both |
| Model check | response `model` must equal the requested id, otherwise the call fails | both |

The two hostnames are what each app was built and tested against; both answered successfully on 2026-10-20 (see [verification](verification.md)). The model id, endpoints and prices are also listed in Nebius's [token-factory cookbook](https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/nemotron3-ultra-550b-a55b.md). The authenticated `GET /v1/models` response we received listed the model with prompt/completion prices of `0.000001` / `0.000003` USD per token.

No SDK is used: both apps make the HTTPS request with the Python standard library, so the request body is visible in a few lines of code.

---

## A. Ask the Three — organizer and judge

Code: [`apps/ask-the-three/ask_three_en/`](../apps/ask-the-three/ask_three_en/)

```
POST /api/stories/{id}/text ──► ai.organize_story ──► providers.nebius_complete(schema "story_summary")
                                   │  one repair call if the JSON fails our own validation
                                   ▼
               REVIEW: user sees the neutral A / B summary and approves it
                                   ▼
POST /api/stories/{id}/approve ──► three threads, same approved input:
     nemotron ─► ai.run_member ─► providers.nebius_complete(schema "panel_result")
     gpt      ─► OpenAI API / local CLI / labelled fixture
     claude   ─► Anthropic API / local CLI / labelled fixture
                                   ▼
          WAITING (API exposes no choice until every seat is COMPLETED or FAILED)
                                   ▼
                    REVEALED: all three slips at once + tally
```

**The call** — `providers.nebius_complete()`:

```python
data = post_json(base + "/chat/completions", {
    "model": model,                                   # nvidia/Nemotron-3-Ultra-550b-a55b
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0,
    "max_tokens": MAX_TOKENS,                         # 1,200
    "response_format": {"type": "json_schema", "json_schema": {
        "name": schema_name, "schema": schema, "strict": True}},
    "chat_template_kwargs": {"enable_thinking": False},
}, {"Authorization": "Bearer " + key}, "nebius")
if data.get("model") != model:
    raise ProviderError("nebius_model_mismatch")      # never accept a substitution
```

**Nemotron's two roles**

1. **Organizer.** Turns a free-form account (typed, or transcribed by Gemini Live STT) into `title`, `context`, `subject`, `entities` and two sides `side_a` / `side_b` (each a `label` and `position`) — a neutral framing both people could accept. The user reviews it before any judge sees it.
2. **Judge (the "Nemotron" seat).** Receives only the approved summary and returns `choice` (A/B), `strength` (`CLOSE` / `LEAN` / `STRONG`), `reasoning`, `other_side_credit` and a `suggestion`. One seat receives the sides in reversed order and its answer is mapped back, so position bias does not line up across judges. No seat sees another's answer.

**Parsing.** `domain.organized()` and `domain.panel_result()` validate the JSON against the app's own rules (required fields, enum values, length limits). A parse/schema failure gets one fresh repair call; anything else becomes a bounded error code (`nebius_http_401`, `nebius_model_mismatch`, `nebius_timeout`, `nebius_oversize`, …). Keys, prompts and response bodies are never logged — only provider, model, token usage, latency and finish reason (`_record_usage`).

**Live vs fixture.** A seat is `live: true` only when its provider is configured (`config.py`). Without `NEBIUS_API_KEY`, the organizer is `fixture` and works **only** for the bundled sample stories, with their prepared summaries labelled *prepared sample — not AI*. Fixture seats return prepared example answers stamped **DEMO FIXTURE** on the card, in `/health`, in `/api/config` and in saved stories. The aggregate keeps `live_votes` separately from the displayed tally, and the verdict screen prints e.g. *"1 live AI vote · 2 demo fixtures (prepared, not live AI)"*. **A live seat that fails stays failed** and is shown as failed; it never falls back to a fixture.

**What we observed on the real Pi (2026-10-19, English mode):** a synthetic spoken story went browser → Pi WebSocket proxy → home server → Gemini Live transcription → Nemotron organizer → Nemotron and GPT (Codex CLI) judges live, Claude a disclosed fixture because its CLI account had hit a usage limit. The screen read **"2 live AI votes · 1 demo fixture (prepared, not live AI)"** — [screenshot](../assets/screenshots/pi/pi-ask-verdict.png). With only a Nebius key, this repository reproduces **1 live vote · 2 demo fixtures**.

## B. OTAKU Gallery — AI Research Guide

Code: [`apps/otaku-gallery/otaku_gallery/`](../apps/otaku-gallery/otaku_gallery/)

```
tap tag / search ─► POST /api/research {query | item_id+topic_id}
                     ResearchManager.start ─► worker thread ─► _run:
   1. evidence.gather_evidence: English Wikipedia + AniList public APIs (or bundled snapshot)
      → records {id, provider, title, url, license, text ≤ bounded}
   2. NebiusWriter.write(query, records)  ── Nemotron writes JSON that cites record ids only
   3. research.build_page: ids → real URLs; names/numbers matched against cited text;
      unmatched passages kept but flagged, confidence lowered
   4. page {title, overview, sections, facts, related, limits, sources[], model, provider, usage}
GET /api/research/{id} (poll) ─► web/research.js renders badges, citation numbers, source list
```

**The call** — `NebiusWriter.build_payload()` / `write()`:

```python
{"model": "nvidia/Nemotron-3-Ultra-550b-a55b",
 "messages": [{"role": "user", "content": PROMPT_with_query_and_numbered_evidence}],
 "temperature": 0, "max_tokens": 4000,
 "response_format": {"type": "json_schema",
                     "json_schema": {"name": "research_page", "schema": SCHEMA, "strict": True}},
 "chat_template_kwargs": {"enable_thinking": False}}
```

`write()` bounds request size, response size (oversize → error), socket and wall time, supports cancellation (the newest search supersedes an older one), checks `finish_reason == "stop"`, rejects tool calls and a mismatched `model`, then validates the JSON against `SCHEMA` locally before use.

**Nemotron's role.** It is a *writer over supplied evidence*, not a search engine: it cannot pick URLs, call tools or see the artwork. The server decides what evidence exists; the model may only cite record ids it was given (`_ids()` drops unknown ids). `build_page()` then checks names and numbers in each paragraph against the cited text — a mechanical safeguard, explicitly *not* proof of semantic accuracy, which the page itself says.

**Live vs demo.** Without a key, or when the provider fails (HTTP error, timeout, schema error, truncated output), the page is an **evidence-only page**: verbatim source excerpts under the heading *Source excerpts* with *"The AI summary is unavailable, so these are verbatim excerpts from the sources."* and the specific reason (e.g. no key configured). It is never presented as an AI answer. A live page carries the badge **NVIDIA Nemotron 3 Ultra** and the provider/model/usage fields.

## Where it shows up in the kiosk

| Kiosk event | What runs |
|---|---|
| Profile `otaku`, nothing else on screen | `otaku-en-host.js` overlays `/otaku-en/?kiosk=1` (the full OTAKU app) on the renderer |
| Tap artwork → details → topic tag, or search field + on-screen keyboard | Research Guide → Nemotron (live) or source excerpts (demo); the host takes the `otaku-en-research` overlay lease so the gallery does not advance |
| Voice "Ask the three…" (simulated by the stage button) | SSE `{"type":"ask_overlay","action":"open"}` → `ask-overlay.js` opens `/ask-en/` in the overlay after the spoken reply finishes |
| Any voice turn, the week calendar, Ask | the OTAKU iframe is hidden and any open research is closed and released |

## Cost and latency we measured

| Call (2026-10-20, from this repository) | Tokens (prompt + completion) | Latency | Estimated cost |
|---|---|---|---|
| Ask the Three single judge (`smoke-nemotron`) | 362 + 113 | 1.67 s | $0.0007 |
| Ask the Three organizer + judge, full story through the kiosk proxy | n/a (two calls) | 2.0 s + 2.1 s | — |
| Research Guide page (`model_smoke.py`, fixture evidence) | 939 + 934 | 2.84 s | $0.0037 |

Estimates use the listed $1 / $3 per million input / output tokens; actual billing was not read.
