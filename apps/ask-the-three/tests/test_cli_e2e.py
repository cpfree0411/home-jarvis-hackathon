"""Exercise the installed CLI and full HTTP workflow in a real child server."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def test_cli_server_and_python_e2e(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, ASK_THREE_STATE=str(tmp_path / "state"))
    base = f"http://127.0.0.1:{port}/"
    with (tmp_path / "server.log").open("w+") as log:
        server = subprocess.Popen([sys.executable, "-m", "ask_three_en.cli", "serve", "--port", str(port)],
                                  env=env, stdout=log, stderr=log, cwd=tmp_path)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                assert server.poll() is None, "CLI server exited before readiness"
                try:
                    with urllib.request.urlopen(base + "health", timeout=1) as response:
                        health = json.load(response)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("CLI server did not become healthy")
            assert health["ok"] and health["edition"] == "en"
            assert all(not s["live"] for s in health["panel"])
            for path, signature in (("", b'lang="en"'), ("app.js", b"Ask the Three"),
                                    ("style.css", b"@font-face"), ("fonts/Gaegu-Bold-latin.woff2", b"wOF2")):
                with urllib.request.urlopen(base + path) as response:
                    assert signature in response.read()
            result = subprocess.run([sys.executable, str(ROOT / "scripts/smoke_e2e.py"), base],
                                    capture_output=True, text=True, timeout=30, check=True)
            summary = json.loads(result.stdout)
            assert summary["E2E"] == "PASS" and summary["aggregate"]["live_votes"] == 0
            assert summary["embargo_leaks"] == 0
            live_required = subprocess.run([sys.executable, str(ROOT / "scripts/smoke_e2e.py"), base,
                                            "--require-live"], capture_output=True, text=True, timeout=30)
            assert live_required.returncode == 1
            assert json.loads(live_required.stdout)["E2E"] == "FAIL"
        finally:
            server.terminate()
            server.wait(timeout=10)
