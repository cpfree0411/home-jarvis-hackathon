# Feedback: Nebius Token Factory and NVIDIA Nemotron

Written from our own logs of 2026-10-19 and 2026-10-20. Anything we did not measure is marked **Needs verification**.

## What we used

- **Service:** Nebius Token Factory, OpenAI-compatible `POST /v1/chat/completions` and `GET /v1/models`, API-key auth. No SDK — plain HTTPS from Python's standard library.
- **Production model:** `nvidia/Nemotron-3-Ultra-550b-a55b` (Ask the Three organizer + judge; OTAKU Research Guide writer).
- **Also tried:** `nvidia/Nemotron-3.5-Super-VL` (vision), `nvidia/nemotron-3-super-120b-a12b`, Nemotron 3 Nano 30B and Nemotron 3.5 Lightning (text). Exact ids for Nano/Lightning: **Needs verification** (recorded only in our private evaluation notes).
- **Not used:** fine-tuning, batch, embeddings, dedicated endpoints, streaming.

## Setting it up

Getting from key to first successful call took one short script: the endpoint is OpenAI-compatible, so the request body is the familiar `model` / `messages` / `response_format`. `GET /v1/models` (HTTP 200, ~0.9 s) returned the model id, a description and per-token prices, which we used to check that the exact model exists before spending anything. The [token-factory cookbook](https://github.com/nebius/token-factory-cookbook) page for Nemotron 3 Ultra gave the id and an example.

Two things took extra digging:

1. **Turning reasoning off.** We wanted direct, reproducible JSON. The switch, `chat_template_kwargs: {"enable_thinking": false}`, came from NVIDIA's model card rather than the Nebius API reference, which accepts extra fields but does not name this one. We confirmed it works empirically: `reasoning_tokens = 0` on every call in our 10-call benchmark.
2. **Two hostnames.** Our apps ended up on `api.tokenfactory.nebius.com` and `api.tokenfactory.us-central1.nebius.com`, both of which worked. Which one is canonical, and whether they differ in routing or limits, is **Needs verification**.

## Requests that worked

All with `temperature: 0`, strict `json_schema`, thinking off, no tools:

| Call | Result |
|---|---|
| Ask the Three judge (`smoke-nemotron`, 2026-10-20) | HTTP 200, served model = requested, 362 + 113 tokens, **1.67 s**, schema-valid |
| Ask the Three organizer + judge, full story via our proxy (2026-10-20) | both 200, organize **2.0 s**, panel **2.1 s** |
| Research Guide page (`model_smoke.py`, 2026-10-20) | HTTP 200, 939 + 934 tokens, **2.84 s**, schema-valid |
| Research Guide via touch in the kiosk (2026-10-20, ×2) | cited English pages rendered |
| Super 120B vs Ultra 550B benchmark (2026-10-19, 5 + 5 calls) | 10/10 HTTP 200, `finish_reason: stop`, strict JSON valid; median round trip 4.28 s vs **3.94 s** |
| Nemotron 3.5 Super VL vision smoke (2026-10-19, 3 images) | 3/3 HTTP 200, 2.05 / 3.58 / 3.15 s, 14/14 correct on simple synthetic images |

Responses always echoed the exact `model` we requested; our "reject a substituted model" guard never fired. We did not see HTTP 429 or 5xx during these runs. Rate limits and behaviour under sustained load: **Needs verification**.

## Quality

- **Structured output is the standout.** With strict `json_schema`, every Ultra response in the runs listed above was schema-valid on the first try. How often Ask the Three's one-repair-call path triggers over many stories: **Needs verification**.
- **As a judge** (English), Nemotron returned a choice, strength, reasoning and a "credit to the other side" that read sensibly on our fictional stories. We have not measured judge consistency or position bias at scale (**Needs verification**); the app reverses the A/B order for one seat to reduce that risk.
- **As a writer over evidence** (English), Ultra writes fluent, well-organized pages and stays mostly inside the supplied text. In our stricter Korean benchmark both Super and Ultra occasionally added facts not in the evidence and made Korean naming errors; Ultra was better. That is why the Research Guide shows numbered sources, mechanically checks names/numbers, and tells the reader to follow the citations.
- **Small models** (Nano 30B, Lightning) were not good enough for our grounded Korean task: truncation (Nano) or unsupported facts slipping past validation (Lightning).

## Latency and cost

Ultra round trips were 1.7–4.3 s for our prompts (non-streaming, from a home server in Korea). Fast enough that a judge's slip is ready before the others in a three-judge reveal, and a research page appears in about the time it takes to read its title. At the listed $1 / $3 per million input/output tokens, an Ask the Three story (organizer + judge) costs well under one US cent, and a Research Guide page about $0.004. Our whole evaluation and development usage on 2026-10-19 was a few cents by our estimates. Actual invoiced amounts: **Needs verification** (we did not read billing).

## What we'd like to see

1. Document `chat_template_kwargs.enable_thinking` (and any other model-specific controls) in the API reference for each Nemotron model.
2. State plainly which base URL to use and whether regional hostnames behave differently.
3. Include modality (text / image) and context length in `GET /v1/models`; today the vision capability had to be confirmed by trying it.
4. Return cost or price-per-call in the response `usage`, so apps can show spend without hard-coding prices.
5. Publish rate limits per model and per key, and the headers to watch.

## Will we keep using it?

**Yes.** Nemotron 3 Ultra already sits on the household's real Ask the Three panel (Korean) and powers the English Research Guide. Reasons: strict-schema reliability, latency that suits a living-room screen, an OpenAI-compatible API that needed no SDK, and low cost per interaction. We will keep source citations and human-visible checks around any factual writing.
