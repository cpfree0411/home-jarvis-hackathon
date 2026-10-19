"""Command line: `ask-three-en serve | check | smoke-nemotron | smoke-stt`."""
from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from . import __version__, ai, config, providers, samples


def load_env_file(path: Path):
    """Minimal KEY=VALUE reader. Existing environment variables win; values are never printed."""
    if not path.is_file():
        raise SystemExit(f"env file not found: {path}")
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"warning: {path} is readable by other users; run: chmod 600 {path}", file=sys.stderr)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _settings(args) -> config.Settings:
    if getattr(args, "env_file", None):
        load_env_file(Path(args.env_file).expanduser())
    if getattr(args, "host", None):
        os.environ["ASK_THREE_HOST"] = args.host
    if getattr(args, "port", None):
        os.environ["ASK_THREE_PORT"] = str(args.port)
    try:
        return config.load()
    except config.ConfigError as exc:
        raise SystemExit(f"configuration error: {exc}") from None


def cmd_check(args) -> int:
    s = _settings(args)
    print(f"Ask the Three (English) {__version__}")
    print(f"  listen        http://{s.host}:{s.port}/")
    print(f"  state dir     {s.state_dir}")
    print(f"  database      {s.db}")
    print(f"  organizer     {s.organizer} ({s.organizer_model if s.organizer == 'nebius' else 'prepared samples only'})")
    for seat in config.SEATS:
        ident = ai.seat_identity(s, seat)
        print(f"  seat {seat:<9}{ident['provider']:<11}{ident['model']}{'' if ident['live'] else '   (demo fixture, not live AI)'}")
    print(f"  speech input  {s.stt}{' ' + s.stt_language if s.stt != 'off' else ' (typing and samples only)'}")
    print(f"  NEBIUS_API_KEY {'set' if config.nebius_key_present() else 'not set'}")
    if s.host not in ("127.0.0.1", "::1", "localhost"):
        print(f"  note: listening beyond loopback; allowed clients = {', '.join(s.allowed_clients)}")
    return 0


def cmd_serve(args) -> int:
    s = _settings(args)
    import uvicorn

    from .app import create_app
    s.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cmd_check(args)
    sys.stdout.flush()
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_level="info", access_log=False,
                proxy_headers=False, server_header=False)
    return 0


def _nebius_models(base: str) -> list[dict]:
    key = providers._key("NEBIUS_API_KEY", "nebius_key_unavailable")
    from urllib.parse import urlsplit
    parts = urlsplit(base)
    conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=30)
    try:
        conn.request("GET", parts.path + "/models?verbose=true",
                     headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise providers.ProviderError(f"nebius_models_http_{resp.status}")
        return json.loads(resp.read(2_000_000)).get("data", [])
    finally:
        conn.close()


def cmd_smoke_nemotron(args) -> int:
    """One real Nemotron judge call on the synthetic haircut sample. Prints counts, never text or keys."""
    s = _settings(args)
    if not args.yes:
        print("This makes one paid Nebius Token Factory call (a fraction of a cent). Re-run with --yes.")
        return 2
    models = {m["id"]: m for m in _nebius_models(s.nebius_base)}
    model = models.get(s.nemotron_model)
    print(json.dumps({"model_listed": model is not None, "model": s.nemotron_model,
                      "description": (model or {}).get("description"),
                      "pricing_per_token": {k: (model or {}).get("pricing", {}).get(k)
                                            for k in ("prompt", "completion")}}))
    if not model:
        return 1
    sample = samples.BY_ID["haircut"]
    prompt = ai.panel_prompt(sample["organized"], False)
    raw = providers.nebius_complete(prompt, "panel_result", providers.PANEL_SCHEMA, s.nemotron_model, s.nebius_base)
    from .domain import panel_result
    result = panel_result(raw, False)
    usage = dict(providers.last_usage)
    price = model.get("pricing", {})
    cost = (usage.get("prompt_tokens", 0) * float(price.get("prompt", 0)) +
            usage.get("completion_tokens", 0) * float(price.get("completion", 0)))
    ascii_share = sum(c.isascii() for c in raw) / max(1, len(raw))
    print(json.dumps({"NEMOTRON_SMOKE": "PASS", "served_model": usage.get("model"), "choice": result["choice"],
                      "strength": result["strength"], "usage": usage, "estimated_cost_usd": round(cost, 6),
                      "ascii_share": round(ascii_share, 3),
                      "reasoning_chars": len(result["reasoning"])}))
    if args.show_text:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


def cmd_smoke_stt(args) -> int:
    """Stream a short WAV/FLAC test file through the configured live transcription."""
    s = _settings(args)
    from .speech import GeminiTranscribeLive
    pcm = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", args.audio, "-f", "s16le",
                          "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", "pipe:1"],
                         check=True, capture_output=True, timeout=30).stdout
    if not 3200 <= len(pcm) <= 32000 * 60:
        raise SystemExit("test audio must be 0.1-60 seconds")

    async def chunks():
        for offset in range(0, len(pcm), 3200):
            yield pcm[offset:offset + 3200]
            await asyncio.sleep(0.1)

    async def run():
        interim, final = 0, ""
        async for event in GeminiTranscribeLive(s.stt_language).stream(chunks()):
            if event["type"] == "interim":
                interim += 1
            elif event["type"] == "complete":
                final = event["text"]
        return interim, final

    interim, final = asyncio.run(run())
    print(json.dumps({"STT_SMOKE": "PASS" if final else "FAIL", "model": GeminiTranscribeLive.MODEL,
                      "language": s.stt_language, "interim_events": interim, "final_chars": len(final)}))
    if args.show_text:
        print(final)
    return 0 if final else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ask-three-en", description="Ask the Three - English edition")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn, extra in (("serve", cmd_serve, True), ("check", cmd_check, True),
                            ("smoke-nemotron", cmd_smoke_nemotron, False), ("smoke-stt", cmd_smoke_stt, False)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--env-file", help="KEY=VALUE file to load (existing environment wins)")
        if extra:
            p.add_argument("--host")
            p.add_argument("--port", type=int)
    sub.choices["smoke-nemotron"].add_argument("--yes", action="store_true", help="confirm one paid call")
    sub.choices["smoke-nemotron"].add_argument("--show-text", action="store_true")
    sub.choices["smoke-stt"].add_argument("audio")
    sub.choices["smoke-stt"].add_argument("--show-text", action="store_true")
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except providers.ProviderError as exc:
        print(f"provider error: {exc.code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
