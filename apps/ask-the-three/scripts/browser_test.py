#!/usr/bin/env python3
"""Run the synthetic browser suite with an isolated server; never calls providers."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="screenshot and QA JSON directory")
    args = parser.parse_args()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("ASK_THREE_") and k not in {
               "NEBIUS_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}/"
    with tempfile.TemporaryDirectory(prefix="ask-three-browser-") as tmp:
        with open(Path(tmp) / "server.log", "w+") as log:
            server = subprocess.Popen([sys.executable, "scripts/ui_fixture_server.py", str(port), tmp],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError("fixture server exited")
                    try:
                        with urllib.request.urlopen(base + "health", timeout=1):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("fixture server did not start")
                return subprocess.call([sys.executable, "scripts/ui_capture.py", "fixture", base,
                                        str(args.output.resolve())], cwd=ROOT, env=env)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
