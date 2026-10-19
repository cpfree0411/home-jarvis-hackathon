"""Showcase server contract tests. Loopback only; no keys, no network, no paid calls."""

from __future__ import annotations

import datetime as dt
import http.client
import json
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "kiosk"))
import showcase  # noqa: E402


class FakeApp(BaseHTTPRequestHandler):
    """Stands in for Ask the Three / OTAKU Gallery behind the proxy."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._reply(200, {"ok": True, "panel": [{"seat": "nemotron", "provider": "fixture",
                                                            "model": "demo-fixture", "live": False}],
                                     "model": "nvidia/Nemotron-3-Ultra-550b-a55b", "nebius_configured": False})
        return self._reply(200, {"path": self.path, "host": self.headers.get("Host"),
                                 "origin": self.headers.get("Origin")})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        return self._reply(201, {"path": self.path, "body": self.rfile.read(n).decode()})


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def server():
    showcase.STORE.__init__()
    app = serve(FakeApp)
    ws_listener = socket.socket()
    ws_listener.bind(("127.0.0.1", 0))
    ws_listener.listen(1)

    def ws_upstream():
        conn, _ = ws_listener.accept()
        head = b""
        while b"\r\n\r\n" not in head:
            head += conn.recv(4096)
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        conn.sendall(b"HEAD:" + head.split(b"\r\n", 1)[0])
        try:
            conn.sendall(b"ECHO:" + conn.recv(4096))
        except OSError:
            pass
        finally:
            conn.close()
    threading.Thread(target=ws_upstream, daemon=True).start()

    showcase.Handler.upstreams = {"/ask-en/": f"http://127.0.0.1:{app.server_port}",
                                  "/otaku-en/": f"http://127.0.0.1:{ws_listener.getsockname()[1]}"}
    srv = serve(showcase.Handler)
    yield srv.server_port
    srv.shutdown()
    app.shutdown()
    ws_listener.close()


def req(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = None if body is None else json.dumps(body)
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    ctype = resp.getheader("Content-Type") or ""
    return resp.status, (json.loads(raw) if "json" in ctype else raw)


def test_kiosk_and_stage_are_served(server):
    status, html = req(server, "GET", "/web/index.html")
    assert status == 200 and b"week-calendar.js" in html and b"otaku-en-host.js" in html
    status, stage = req(server, "GET", "/")
    assert status == 200 and b"Simulated" in stage


def test_path_traversal_is_refused(server):
    for path in ("/web/../showcase.py", "/web/%2e%2e/showcase.py", "/media/art/../../../README.md"):
        status, _ = req(server, "GET", path)
        assert status == 404, path


def test_media_playlist_points_at_bundled_cc0_art(server):
    status, media = req(server, "GET", "/api/media?profile=otaku")
    assert status == 200 and media["profile"] == "otaku" and len(media["items"]) == 8
    for item in media["items"]:
        status, svg = req(server, "GET", item["url"])
        assert status == 200 and svg.lstrip().startswith(b"<svg")
    status, check = req(server, "GET", "/api/media?check=1")
    assert check["count"] == 8 and "items" not in check


def test_calendar_is_fictional_and_relative_to_today(server):
    today = dt.datetime.now(showcase.TZ).date()
    monday = today - dt.timedelta(days=today.weekday())
    status, cal = req(server, "GET", f"/api/calendar?start={monday}&end={monday + dt.timedelta(days=7)}")
    assert status == 200 and cal["sample_data"] is True
    titles = {e["title"] for e in cal["events"]}
    assert "Hackathon demo" in titles and len(cal["events"]) >= len(showcase.WEEK_TEMPLATE)
    assert {e["calendar_id"] for e in cal["events"]} <= {c["id"] for c in showcase.CALENDARS}
    for bad in ("start=x&end=y", f"start={monday}&end={monday}", f"start={monday}&end={monday + dt.timedelta(days=90)}"):
        assert req(server, "GET", "/api/calendar?" + bad)[0] == 400


def test_voice_proposal_then_touch_confirm_moves_event_in_memory(server):
    status, out = req(server, "POST", "/api/demo/scenario", {"name": "week_move"})
    assert status == 200 and out["simulated"] is True
    (op, proposal), = showcase.STORE.proposals.items()
    status, res = req(server, "POST", "/api/calendar/mutation/confirm", {"operation_id": op})
    assert status == 200 and "sample data" in res["summary_line"]
    day = proposal["target"]["start"][:10]
    nxt = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
    _, cal = req(server, "GET", f"/api/calendar?start={day}&end={nxt}")
    demo = next(e for e in cal["events"] if e["title"] == "Hackathon demo")
    assert demo["start"] == proposal["changes"]["start"]
    # A second confirm of the same question is refused; reset restores the sample week.
    assert req(server, "POST", "/api/calendar/mutation/confirm", {"operation_id": op})[0] == 409
    req(server, "POST", "/api/demo/reset", {})
    _, cal = req(server, "GET", f"/api/calendar?start={day}&end={nxt}")
    assert next(e for e in cal["events"] if e["title"] == "Hackathon demo")["start"] == proposal["target"]["start"]


def test_cancel_clears_the_question(server):
    req(server, "POST", "/api/demo/scenario", {"name": "week_move"})
    (op, _), = showcase.STORE.proposals.items()
    assert req(server, "POST", "/api/calendar/mutation/cancel", {"operation_id": op})[0] == 200
    assert not showcase.STORE.proposals and not showcase.STORE.moved


def test_scenarios_broadcast_the_production_message_shapes(server):
    q = showcase.STORE.subscribe()
    assert q.get(timeout=1) == {"type": "state", "name": "idle", "loop": True}
    req(server, "POST", "/api/demo/scenario", {"name": "week_next"})
    msg = q.get(timeout=2)
    assert msg["type"] == "calendar" and msg["action"] == "open" and msg["view"] == "week"
    req(server, "POST", "/api/demo/scenario", {"name": "week_skin", "skin": "tape"})
    assert q.get(timeout=2) == {"type": "week_skin", "skin": "tape"}
    assert req(server, "GET", "/api/calendar/week-skin")[1]["skin"] == "tape"
    assert req(server, "POST", "/api/demo/scenario", {"name": "nope"})[0] == 400
    showcase.STORE.unsubscribe(q)


def test_ask_scenario_ends_with_deferred_overlay_open():
    steps = showcase.scenario("ask_three")
    assert steps[-1][1] == {"type": "ask_overlay", "action": "open"}
    states = [m["name"] for _, m in steps if m["type"] == "state"]
    assert states[0] == "listening" and states[-1] == "idle"


def test_sse_stream_delivers_messages(server):
    conn = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    conn.request("GET", "/api/events")
    resp = conn.getresponse()
    assert resp.getheader("Content-Type").startswith("text/event-stream")
    assert json.loads(resp.fp.readline().decode()[len("data: "):]) ["name"] == "idle"
    resp.fp.readline()
    showcase.STORE.broadcast({"type": "caption", "text": "hello "}, critical=False)
    assert json.loads(resp.fp.readline().decode()[len("data: "):]) == {"type": "caption", "text": "hello "}
    conn.close()


def test_cross_origin_posts_are_refused(server):
    status, _ = req(server, "POST", "/api/demo/scenario", {"name": "week_open"},
                    headers={"Origin": "http://evil.example"})
    assert status == 403


def test_proxy_strips_prefix_and_keeps_public_host(server):
    status, out = req(server, "GET", "/ask-en/api/config?x=1", headers={"Origin": "http://127.0.0.1"})
    assert status == 200 and out["path"] == "/api/config?x=1"
    assert out["host"] == f"127.0.0.1:{server}"
    status, out = req(server, "POST", "/ask-en/api/stories", {"source": "sample"})
    assert status == 201 and json.loads(out["body"]) == {"source": "sample"}
    conn = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    conn.request("GET", "/ask-en")
    resp = conn.getresponse()
    assert resp.status == 301 and resp.getheader("Location") == "/ask-en/"


def test_websocket_upgrade_is_tunnelled(server):
    sock = socket.create_connection(("127.0.0.1", server), timeout=5)
    sock.sendall(b"GET /otaku-en/ws/transcribe/abc HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                 b"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: x\r\n"
                 b"Sec-WebSocket-Version: 13\r\n\r\n")
    data = b""
    deadline = time.time() + 5
    while b"HEAD:" not in data and time.time() < deadline:
        data += sock.recv(4096)
    assert data.startswith(b"HTTP/1.1 101") and b"HEAD:GET /ws/transcribe/abc HTTP/1.1" in data
    sock.sendall(b"\x82\x03pcm")
    echo = b""
    while b"ECHO:" not in echo and time.time() < deadline:
        echo += sock.recv(4096)
    assert echo.endswith(b"ECHO:\x82\x03pcm")
    sock.close()


def test_status_reports_live_flags_from_upstreams(server):
    _, s = req(server, "GET", "/api/showcase")
    assert s["simulated_voice_agent"] is True
    assert s["ask_the_three"]["live_seats"] == 0 and s["ask_the_three"]["seats"][0]["live"] is False
    assert s["otaku_gallery"]["nemotron_live"] is False


def test_unreachable_app_is_a_clear_error():
    showcase.Handler.upstreams = {"/ask-en/": "http://127.0.0.1:9", "/otaku-en/": "http://127.0.0.1:9"}
    srv = serve(showcase.Handler)
    try:
        status, out = req(srv.server_port, "GET", "/ask-en/")
        assert status == 502 and out["error"] == "upstream_unavailable"
    finally:
        srv.shutdown()


def test_kiosk_has_no_hangul_or_private_addresses():
    banned = re.compile("[%s-%s]" % (chr(0xAC00), chr(0xD7A3)) +
                        r"|192\.168\.|/home/[a-z]+/|@gmail\.com", re.I)
    for path in (REPO / "kiosk").rglob("*"):
        if path.is_file() and path.suffix in (".js", ".css", ".html", ".py", ".cjs", ".svg", ".json"):
            hits = banned.findall(path.read_text(encoding="utf-8"))
            assert not hits, f"{path.relative_to(REPO)}: {hits[:3]}"
