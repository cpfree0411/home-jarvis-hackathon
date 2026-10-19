#!/usr/bin/env python3
"""Start the whole Home Jarvis showcase with one command.

Three local processes, all bound to loopback by default:

  * Ask the Three (apps/ask-the-three)   default :8794
  * OTAKU Gallery EN (apps/otaku-gallery) default :8805
  * Kiosk showcase (kiosk/showcase.py)    default :8780, proxies the two apps

Live mode: NEBIUS_API_KEY comes from the process environment or from --env-file
(default ./.env when present). Optional GPT/Claude/Gemini keys are passed to
Ask the Three the same way. --demo removes every provider key, so no paid call
can happen and both apps show their labelled demo behaviour.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN = Path(sys.executable).parent
STATE = REPO / ".state"
PROVIDER_KEYS = ("NEBIUS_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY")
LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def read_env_file(path: Path) -> dict[str, str]:
    """Simple KEY=VALUE lines; no shell expansion. Existing environment wins."""
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = LINE.match(raw)
        if not m:
            continue
        value = m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[m.group(1)] = value
    return values


def port_free(host: str, port: int) -> bool:
    with socket.socket() as sock:
        # Same option the servers use, so sockets lingering in TIME_WAIT after
        # a restart don't count as busy; a live listener still does.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def wait_health(url: str, proc: subprocess.Popen, name: str, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"{name} exited with code {proc.returncode} during startup (see output above).")
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.3)
    raise SystemExit(f"{name} did not become healthy at {url} within {timeout:.0f}s.")


def build_envs(args, environ):
    """Return (showcase, ask, otaku) environments for the given CLI args."""
    base_env = dict(environ)
    env_file = args.env_file or (REPO / ".env")
    if args.env_file and not args.env_file.is_file():
        raise SystemExit(f"Env file not found: {args.env_file}")
    if not args.demo and env_file.is_file():
        for k, v in read_env_file(env_file).items():
            base_env.setdefault(k, v)
    if args.demo:
        for k in PROVIDER_KEYS:
            base_env.pop(k, None)
        for k in list(base_env):
            if k.startswith("ASK_THREE_SEAT_") or k in ("ASK_THREE_ORGANIZER", "ASK_THREE_STT"):
                base_env.pop(k)
        base_env.update({"ASK_THREE_ORGANIZER": "fixture", "ASK_THREE_SEAT_NEMOTRON": "fixture",
                         "ASK_THREE_SEAT_GPT": "fixture", "ASK_THREE_SEAT_CLAUDE": "fixture",
                         "ASK_THREE_STT": "off"})

    origins = sorted(f"http://{h}:{args.port}" for h in {args.host, "127.0.0.1", "localhost"})
    state = args.state_dir.resolve()
    ask_env = dict(base_env, ASK_THREE_STATE=str(state / "ask"),
                   ASK_THREE_ALLOWED_ORIGINS=",".join(origins + [f"http://127.0.0.1:{args.ask_port}"]))
    otaku_env = dict(base_env, OTAKU_HOST=args.host, OTAKU_PORT=str(args.otaku_port),
                     OTAKU_ALLOWED_ORIGINS=",".join(origins), XDG_STATE_HOME=str(state / "otaku"),
                     OTAKU_LOCAL_MANIFEST=str(state / "otaku" / "no-local-gallery.json"))
    # The gallery only ever needs the Nebius key.
    for k in [k for k in otaku_env if k.startswith(("OPENAI_", "ANTHROPIC_", "GEMINI_", "GOOGLE_"))]:
        otaku_env.pop(k)
    # The kiosk server itself never needs a provider key.
    kiosk_env = {k: v for k, v in base_env.items() if k not in PROVIDER_KEYS}
    return kiosk_env, ask_env, otaku_env


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="ignore all provider keys (no paid calls)")
    ap.add_argument("--env-file", type=Path, help="KEY=VALUE file with your keys (default: ./.env if present)")
    ap.add_argument("--host", default="127.0.0.1", help="bind address for all three servers")
    ap.add_argument("--port", type=int, default=8780, help="showcase port")
    ap.add_argument("--ask-port", type=int, default=8794)
    ap.add_argument("--otaku-port", type=int, default=8805)
    ap.add_argument("--state-dir", type=Path, default=STATE, help="local app state (default ./.state)")
    args = ap.parse_args(argv)

    kiosk_env, ask_env, otaku_env = build_envs(args, os.environ)
    live = bool(ask_env.get("NEBIUS_API_KEY"))
    state = args.state_dir.resolve()
    (state / "ask").mkdir(parents=True, exist_ok=True)
    (state / "otaku").mkdir(parents=True, exist_ok=True)

    # Refuse to start rather than talk to some other service on a busy port.
    busy = [f"{name} {args.host}:{port}" for name, port in
            (("showcase", args.port), ("Ask the Three", args.ask_port), ("OTAKU Gallery", args.otaku_port))
            if not port_free(args.host, port)]
    if busy:
        raise SystemExit("Port already in use: " + ", ".join(busy) +
                         ". Choose free ports with --port, --ask-port and --otaku-port.")

    procs: list[tuple[str, subprocess.Popen]] = []

    def stop(*_):
        for _, p in reversed(procs):
            if p.poll() is None:
                p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()

    signal.signal(signal.SIGTERM, lambda *a: (stop(), sys.exit(0)))
    try:
        ask = subprocess.Popen([str(BIN / "ask-three-en"), "serve", "--host", args.host,
                                "--port", str(args.ask_port)], env=ask_env, cwd=state / "ask")
        procs.append(("Ask the Three", ask))
        # cwd is the state dir so the gallery never picks up a stray .env/media folder.
        otaku = subprocess.Popen([str(BIN / "otaku-gallery")], env=otaku_env, cwd=state / "otaku")
        procs.append(("OTAKU Gallery", otaku))
        wait_health(f"http://127.0.0.1:{args.ask_port}/health", ask, "Ask the Three")
        wait_health(f"http://127.0.0.1:{args.otaku_port}/health", otaku, "OTAKU Gallery")
        kiosk = subprocess.Popen([sys.executable, str(REPO / "kiosk" / "showcase.py"),
                                  "--host", args.host, "--port", str(args.port),
                                  "--ask-url", f"http://127.0.0.1:{args.ask_port}",
                                  "--otaku-url", f"http://127.0.0.1:{args.otaku_port}"], env=kiosk_env)
        procs.append(("Kiosk showcase", kiosk))
        wait_health(f"http://127.0.0.1:{args.port}/health", kiosk, "Kiosk showcase")
        print("\n  Home Jarvis showcase is running.\n"
              f"    Stage + simulated voice remote : http://127.0.0.1:{args.port}/\n"
              f"    Kiosk only (1024x600)          : http://127.0.0.1:{args.port}/web/index.html?profile=otaku\n"
              f"    Ask the Three                  : http://127.0.0.1:{args.port}/ask-en/\n"
              f"    OTAKU Gallery                  : http://127.0.0.1:{args.port}/otaku-en/?kiosk=1\n"
              f"  Nemotron: {'LIVE (NEBIUS_API_KEY configured)' if live else 'DEMO (no key; labelled fixtures/excerpts)'}\n"
              "  Ctrl+C stops everything.\n", flush=True)
        while all(p.poll() is None for _, p in procs):
            time.sleep(0.5)
        dead = [n for n, p in procs if p.poll() is not None]
        raise SystemExit(f"{', '.join(dead)} stopped unexpectedly.")
    except KeyboardInterrupt:
        pass
    finally:
        stop()


if __name__ == "__main__":
    main()
