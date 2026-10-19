#!/usr/bin/env python3
"""Home Jarvis public showcase server.

Serves the real Home Jarvis kiosk renderer (``kiosk/web``) with the same HTTP
and Server-Sent-Events contract the production Pi server provides, but backed
by fictional sample data instead of a household calendar, Home Assistant, or a
private photo library.

It also reverse-proxies the two English hackathon apps exactly the way the Pi
does in its English exhibition mode:

    /ask-en/    ->  Ask the Three      (apps/ask-the-three, default :8794)
    /otaku-en/  ->  OTAKU Gallery EN   (apps/otaku-gallery, default :8805)

including WebSocket upgrades (Ask the Three streams microphone PCM over one).

The voice agent that drives the real kiosk (Gemini Live on the Pi) is not part
of this repository. ``POST /api/demo/scenario`` replays the same SSE messages
that agent sends, and the stage page labels those buttons as simulated.

Standard library only. Python 3.11+.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import mimetypes
import os
import queue
import select
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
WEB = ROOT / "web"
ART = REPO / "apps" / "otaku-gallery" / "web" / "art"
ART_MANIFEST = REPO / "apps" / "otaku-gallery" / "data" / "gallery.json"

# The production calendar is pinned to the household's zone; the week UI does
# its own Monday-start arithmetic in this zone regardless of the browser's.
TZ = ZoneInfo("Asia/Seoul")
MAX_BODY = 16 * 1024
VERSION = "1.0.0"

log = logging.getLogger("jarvis-showcase")

REGISTRY = {
    "states": {name: {"loop": True} for name in
               ("idle", "listening", "thinking", "searching", "speaking")},
    "events": {
        "welcome_home": {"loop": False, "duration": 8.0},
        "sendoff_work": {"loop": False, "duration": 6.0},
    },
}

WEEK_SKINS = ("riso", "linen", "moonlight", "tape", "ribbon")

# Fictional household. Names, calendars and events are invented for the demo.
PEOPLE = [
    {"id": "alex", "kind": "person", "label": "Alex", "calendar_ids": ["alex"]},
    {"id": "sam", "kind": "person", "label": "Sam", "calendar_ids": ["sam"]},
]
CALENDARS = [
    {"id": "alex", "name": "Alex", "writable": True},
    {"id": "sam", "name": "Sam", "writable": True},
    {"id": "family", "name": "Household", "writable": True},
    {"id": "holidays", "name": "Holidays (sample)", "writable": False},
]
# (weekday 0=Mon, calendar, title, start "HH:MM" or None for all day, minutes)
WEEK_TEMPLATE = [
    (0, "alex", "Design review", "10:00", 60),
    (0, "family", "Recycling day", None, 0),
    (1, "sam", "Pilates", "07:30", 50),
    (1, "alex", "Dentist", "16:00", 45),
    (2, "family", "Grocery delivery", "18:30", 30),
    (2, "sam", "Team lunch", "12:00", 90),
    (3, "alex", "Hackathon demo", "15:00", 60),
    (3, "sam", "Piano lesson", "19:00", 60),
    (4, "family", "Movie night", "20:00", 120),
    (5, "family", "Farmers market", "09:00", 120),
    (5, "alex", "Bike repair", "14:00", 60),
    (6, "sam", "Call with grandparents", "11:00", 30),
    (6, "family", "Meal prep", "17:00", 90),
]


def _art_items():
    try:
        manifest = json.loads(ART_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    items = []
    for entry in manifest.get("items", manifest.get("artworks", [])):
        name = Path(str(entry.get("image") or entry.get("file") or "")).name
        if name and (ART / name).is_file():
            items.append({"id": "art-" + Path(name).stem, "type": "image",
                          "url": "/media/art/" + name, "title": entry.get("title", ""),
                          "width": 1600, "height": 900})
    if not items:
        for path in sorted(ART.glob("*.svg")):
            items.append({"id": "art-" + path.stem, "type": "image",
                          "url": "/media/art/" + path.name, "title": path.stem,
                          "width": 1600, "height": 900})
    return items


class Store:
    """All showcase state. In memory only; a restart resets it."""

    def __init__(self):
        self.lock = threading.RLock()
        self.subscribers: set[queue.Queue] = set()
        self.steady = "idle"
        self.exhibition = "en"           # "en": OTAKU app over the stage
        self.skin = "riso"
        self.requested_profile = "otaku"
        self.active_profile = None
        self.moved: dict[str, dict] = {}  # event id -> override (demo edits)
        self.deleted: set[str] = set()
        self.proposals: dict[str, dict] = {}
        self.ask_open = False
        self.calendar_context = None
        self.scenario_gen = 0

    # ---------------------------------------------------------------- SSE
    def subscribe(self):
        q: queue.Queue = queue.Queue(maxsize=64)
        with self.lock:
            self.subscribers.add(q)
            q.put_nowait({"type": "state", "name": self.steady, "loop": True})
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subscribers.discard(q)

    def broadcast(self, msg, critical=True):
        with self.lock:
            if msg.get("type") == "state":
                self.steady = msg["name"]
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    if critical:
                        dead.append(q)
            for q in dead:
                self.subscribers.discard(q)

    # ----------------------------------------------------------- calendar
    def events(self, start: dt.date, end: dt.date):
        """Sample events for every week in range, generated around today."""
        out = []
        day = start - dt.timedelta(days=start.weekday())
        while day < end:
            for weekday, cal, title, hhmm, minutes in WEEK_TEMPLATE:
                d = day + dt.timedelta(days=weekday)
                out.append(self._event(d, cal, title, hhmm, minutes))
            day += dt.timedelta(days=7)
        holidays = {(10, 31): "Halloween", (12, 25): "Christmas Day", (1, 1): "New Year's Day"}
        d = start
        while d < end:
            if (d.month, d.day) in holidays:
                out.append(self._event(d, "holidays", holidays[(d.month, d.day)], None, 0, writable=False))
            d += dt.timedelta(days=1)
        with self.lock:
            result = []
            for ev in out:
                if ev["id"] in self.deleted:
                    continue
                result.append(dict(ev, **self.moved.get(ev["id"], {})))
        return [ev for ev in result
                if start.isoformat() <= ev["start"][:10] < end.isoformat()]

    @staticmethod
    def _event(d, cal, title, hhmm, minutes, writable=True):
        if hhmm is None:
            start, stop, all_day = d.isoformat(), (d + dt.timedelta(days=1)).isoformat(), True
        else:
            h, m = map(int, hhmm.split(":"))
            s = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)
            start, stop, all_day = s.isoformat(), (s + dt.timedelta(minutes=minutes)).isoformat(), False
        slug = "".join(c for c in title.lower() if c.isalnum())
        return {"id": f"{cal}:{slug}:{start}", "calendar_id": cal, "title": title,
                "start": start, "end": stop, "all_day": all_day, "writable": writable,
                "source_ref": "sample"}


STORE = Store()


# ------------------------------------------------------------------ scenarios
def _today():
    return dt.datetime.now(TZ).date()


def _monday(offset_weeks=0):
    t = _today()
    return t - dt.timedelta(days=t.weekday()) + dt.timedelta(weeks=offset_weeks)


def _say(steps, text):
    """Append a speaking turn whose caption streams in small chunks."""
    steps.append((0.0, {"type": "state", "name": "speaking"}))
    words = text.split(" ")
    for i in range(0, len(words), 3):
        steps.append((0.35, {"type": "caption", "text": " ".join(words[i:i + 3]) + " "}))
    steps.append((2.4, {"type": "state", "name": "idle"}))


def _voice_turn(question, answer, during=None):
    steps = [(0.0, {"type": "state", "name": "listening"}),
             (1.6, {"type": "state", "name": "thinking"})]
    steps.extend(during or [])
    _say(steps, answer)
    return steps


def scenario(name, args=None):
    """Return [(delay_seconds, sse_message)] for a named demo scenario."""
    args = args or {}
    thursday = (_monday() + dt.timedelta(days=3)).isoformat()
    if name == "voice_turn":
        return _voice_turn("What can you do?",
                           "Hi! I'm Home Jarvis. I can show the family week, play music, "
                           "control the lights, read the news, and ask three AI judges "
                           "to settle a friendly argument.")
    if name == "week_open":
        return _voice_turn("What's on this week?",
                           "Here is your week. Thursday looks busiest, with the hackathon "
                           "demo at three and a piano lesson in the evening.",
                           during=[(0.6, {"type": "calendar", "action": "open", "view": "week",
                                          "date": _today().isoformat()})])
    if name == "week_next":
        return [(0.0, {"type": "calendar", "action": "open", "view": "week",
                       "date": _monday(1).isoformat()})]
    if name == "week_prev":
        return [(0.0, {"type": "calendar", "action": "open", "view": "week",
                       "date": _monday(-1).isoformat()})]
    if name == "week_focus":
        return _voice_turn("When is Alex's demo?",
                           "Alex's hackathon demo is on Thursday at three p.m.",
                           during=[(0.4, {"type": "calendar", "action": "select", "view": "week",
                                          "date": thursday,
                                          "focus": {"dates": [thursday], "person": "alex",
                                                    "title": "Hackathon demo"}})])
    if name == "week_move":
        start = dt.datetime.fromisoformat(thursday).replace(hour=15, tzinfo=TZ)
        ev = Store._event(start.date(), "alex", "Hackathon demo", "15:00", 60)
        ev = dict(ev, **STORE.moved.get(ev["id"], {}))
        new_start = dt.datetime.fromisoformat(ev["start"]) + dt.timedelta(hours=1)
        op = f"demo-{int(time.time() * 1000)}"
        proposal = {"operation_id": op, "action": "update", "target": ev,
                    "changes": {"start": new_start.isoformat(),
                                "end": (new_start + dt.timedelta(hours=1)).isoformat()}}
        with STORE.lock:
            STORE.proposals[op] = proposal
        return _voice_turn("Move the demo an hour later.",
                           "Should I move the hackathon demo to four? Tap Change to confirm.",
                           during=[(0.3, {"type": "calendar", "action": "mutation",
                                          "event": "proposal", "proposal": proposal})])
    if name == "week_close":
        return [(0.0, {"type": "calendar", "action": "close"})]
    if name == "week_skin":
        skin = str(args.get("skin", "")).lower()
        if skin not in WEEK_SKINS:
            skin = WEEK_SKINS[(WEEK_SKINS.index(STORE.skin) + 1) % len(WEEK_SKINS)]
        STORE.skin = skin
        return [(0.0, {"type": "week_skin", "skin": skin})]
    if name == "ask_three":
        steps = [(0.0, {"type": "state", "name": "listening"}),
                 (1.4, {"type": "state", "name": "thinking"})]
        _say(steps, "Opening Ask the Three. Tell me what happened, and three AI judges will weigh in.")
        # The Pi defers this hand-off until the spoken reply has drained; the
        # overlay refuses to open while a voice session still owns the screen.
        steps.append((2.0, {"type": "ask_overlay", "action": "open"}))
        return steps
    if name == "welcome_home":
        return [(0.0, {"type": "event", "name": "welcome_home", "steady_state": "idle"})]
    if name == "gallery_app":
        STORE.exhibition = "en"
        return []
    if name == "gallery_renderer":
        STORE.exhibition = "renderer"
        return []
    return None


def run_scenario(steps):
    with STORE.lock:
        STORE.scenario_gen += 1
        gen = STORE.scenario_gen

    def worker():
        for delay, msg in steps:
            time.sleep(delay)
            with STORE.lock:
                if gen != STORE.scenario_gen:
                    return
            STORE.broadcast(msg, critical=msg.get("type") != "caption")
    threading.Thread(target=worker, daemon=True, name="scenario").start()


# ---------------------------------------------------------------- HTTP layer
class Handler(BaseHTTPRequestHandler):
    server_version = "HomeJarvisShowcase/" + VERSION
    protocol_version = "HTTP/1.1"
    upstreams: dict[str, str] = {}

    def log_message(self, fmt, *args):  # noqa: N802 - stdlib signature
        log.debug("%s %s", self.address_string(), fmt % args)

    # -------------------------------------------------------------- helpers
    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urllib.parse.urlparse(origin).netloc == self.headers.get("Host")

    def send_file(self, path: Path, head=False):
        try:
            data = path.read_bytes()
        except OSError:
            return self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def static(self, base: Path, rel: str):
        target = (base / urllib.parse.unquote(rel)).resolve()
        if base.resolve() not in target.parents or not target.is_file():
            return self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        return self.send_file(target, head=self.command == "HEAD")

    # --------------------------------------------------------------- routes
    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_GET(self):  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        path, qs = url.path, urllib.parse.parse_qs(url.query)
        if self.proxy_target(path):
            return self.proxy()
        if path == "/":
            return self.send_file(WEB / "stage.html", head=self.command == "HEAD")
        if path in ("/web", "/web/"):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/web/index.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if path.startswith("/web/"):
            return self.static(WEB, path[len("/web/"):])
        if path.startswith("/media/art/"):
            return self.static(ART, path[len("/media/art/"):])
        if path == "/favicon.ico":
            return self.static(WEB, "favicon.svg")
        if path == "/api/events":
            return self.sse()
        if path in ("/health", "/api/health"):
            return self.send_json(HTTPStatus.OK, self.health())
        if path == "/api/showcase":
            return self.send_json(HTTPStatus.OK, self.showcase_status())
        if path == "/api/registry":
            return self.send_json(HTTPStatus.OK, {"ok": True, "registry": REGISTRY})
        if path == "/api/profile":
            return self.send_json(HTTPStatus.OK, {
                "ok": True, "requested_profile": STORE.requested_profile,
                "active_profile": STORE.active_profile, "pending": False,
                "runnable_profiles": [{"id": "otaku", "name": "OTAKU",
                                       "description": "Original CC0 sample art"}]})
        if path == "/api/media":
            items = _art_items()
            if qs.get("check", ["0"])[0] in ("1", "true"):
                return self.send_json(HTTPStatus.OK, {"ok": True, "profile": "otaku",
                                                      "generation": "showcase-1", "count": len(items)})
            return self.send_json(HTTPStatus.OK, {
                "ok": True, "profile": "otaku", "generation": "showcase-1",
                "personal_revision": 0, "dwell_ms": 24000, "items": items})
        if path == "/api/exhibition":
            return self.send_json(HTTPStatus.OK, {"ok": True, "mode": STORE.exhibition})
        if path == "/api/calendar":
            return self.calendar(qs)
        if path == "/api/calendar/profiles":
            return self.send_json(HTTPStatus.OK, {"ok": True, "profiles": PEOPLE})
        if path == "/api/calendar/week-skin":
            return self.send_json(HTTPStatus.OK, {"ok": True, "skin": STORE.skin, "skins": list(WEEK_SKINS)})
        if path == "/api/otaku/personal/state":
            return self.send_json(HTTPStatus.OK, {"ok": True, "revision": 0, "feedback": {}})
        return self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self):  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if self.proxy_target(path):
            return self.proxy()
        if not self.same_origin():
            return self.send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "origin_not_allowed"})
        try:
            body = self.read_json()
        except ValueError as exc:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        if path == "/api/demo/scenario":
            steps = scenario(str(body.get("name", "")), body)
            if steps is None:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "unknown_scenario"})
            run_scenario(steps)
            return self.send_json(HTTPStatus.OK, {"ok": True, "simulated": True, "steps": len(steps)})
        if path == "/api/demo/reset":
            run_scenario([(0.0, {"type": "calendar", "action": "close"}),
                          (0.0, {"type": "state", "name": "idle"}),
                          (0.0, {"type": "caption", "clear": True})])
            with STORE.lock:
                STORE.moved.clear()
                STORE.deleted.clear()
                STORE.proposals.clear()
            return self.send_json(HTTPStatus.OK, {"ok": True})
        if path == "/api/calendar/week-skin":
            skin = str(body.get("skin", "")).lower()
            if skin not in WEEK_SKINS:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "unknown_skin"})
            STORE.skin = skin
            return self.send_json(HTTPStatus.OK, {"ok": True, "skin": skin})
        if path.startswith("/api/calendar/mutation/"):
            return self.mutation(path.rsplit("/", 1)[-1], body)
        if path == "/api/calendar/context":
            STORE.calendar_context = body
            return self.send_json(HTTPStatus.OK, {"ok": True})
        if path == "/api/profile/applied":
            STORE.active_profile = str(body.get("profile") or body.get("active_profile") or "otaku")
            return self.send_json(HTTPStatus.OK, {"ok": True, "active_profile": STORE.active_profile})
        if path == "/api/ask/overlay":
            action = body.get("action")
            with STORE.lock:
                if action == "opened":
                    STORE.ask_open = True
                    return self.send_json(HTTPStatus.OK, {"ok": True, "status": "open"})
                if action in ("close", "reject"):
                    STORE.ask_open = False
            return self.send_json(HTTPStatus.OK, {"ok": True, "status": "closed"})
        if path in ("/api/ask/session", "/api/event_completed", "/api/calendar/week-skin/rendered",
                    "/api/otaku/context", "/api/briefing/context", "/api/nature/context"):
            if path == "/api/event_completed":
                STORE.broadcast({"type": "state", "name": STORE.steady})
            return self.send_json(HTTPStatus.OK, {"ok": True})
        return self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    do_PUT = do_DELETE = do_PATCH = lambda self: (  # noqa: E731
        self.proxy() if self.proxy_target(urllib.parse.urlparse(self.path).path)
        else self.send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"ok": False, "error": "method_not_allowed"}))

    # ------------------------------------------------------------ endpoints
    def calendar(self, qs):
        try:
            start = dt.date.fromisoformat(qs.get("start", [""])[0])
            end = dt.date.fromisoformat(qs.get("end", [""])[0])
        except ValueError:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "start and end are required (YYYY-MM-DD)"})
        if not 0 < (end - start).days <= 62:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "bad range"})
        return self.send_json(HTTPStatus.OK, {"ok": True, "sample_data": True, "calendars": CALENDARS,
                                              "events": STORE.events(start, end)})

    def mutation(self, verb, body):
        op = str(body.get("operation_id", ""))
        with STORE.lock:
            proposal = STORE.proposals.pop(op, None)
        if proposal is None:
            return self.send_json(HTTPStatus.CONFLICT, {"ok": False, "summary_line": "That question has expired"})
        if verb == "cancel":
            STORE.broadcast({"type": "calendar", "action": "mutation", "event": "proposal_cleared",
                             "operation_id": op, "status": "cancelled"})
            return self.send_json(HTTPStatus.OK, {"ok": True})
        if verb != "confirm":
            return self.send_json(HTTPStatus.NOT_FOUND, {"ok": False})
        target = proposal["target"]
        with STORE.lock:
            if proposal["action"] == "delete":
                STORE.deleted.add(target["id"])
            else:
                STORE.moved[target["id"]] = dict(proposal["changes"])
        when = dt.datetime.fromisoformat(proposal["changes"]["start"]).strftime("%-I:%M %p")
        run_scenario([(0.6, {"type": "calendar", "action": "mutation", "event": "refreshed"})])
        return self.send_json(HTTPStatus.OK, {"ok": True, "sample_data": True,
                                              "summary_line": f"Moved to {when} (sample data, in memory)"})

    def sse(self):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = STORE.subscribe()
        try:
            while True:
                try:
                    msg = q.get(timeout=15.0)
                    self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            STORE.unsubscribe(q)
            self.close_connection = True

    def upstream_health(self, prefix):
        base = self.upstreams.get(prefix)
        if not base:
            return {"reachable": False, "error": "not_configured"}
        try:
            with urllib.request.urlopen(base + "/health", timeout=2.0) as resp:
                return dict(json.loads(resp.read().decode()), reachable=True)
        except (OSError, ValueError) as exc:
            return {"reachable": False, "error": type(exc).__name__}

    def health(self):
        return {"ok": True, "service": "home-jarvis-showcase", "version": VERSION,
                "subscribers": len(STORE.subscribers), "sample_data": True}

    def showcase_status(self):
        ask, otaku = self.upstream_health("/ask-en/"), self.upstream_health("/otaku-en/")
        seats = ask.get("panel") or []
        return {
            "ok": True, "version": VERSION, "exhibition": STORE.exhibition, "skin": STORE.skin,
            "simulated_voice_agent": True, "sample_data": ["calendar", "gallery art", "voice turns"],
            "ask_the_three": {
                "reachable": ask.get("reachable", False),
                "organizer": ask.get("organizer"),
                "seats": [{"seat": s.get("seat"), "provider": s.get("provider"),
                           "model": s.get("model"), "live": bool(s.get("live"))} for s in seats],
                "live_seats": sum(1 for s in seats if s.get("live")),
            },
            "otaku_gallery": {
                "reachable": otaku.get("reachable", False),
                "model": otaku.get("model"),
                "nemotron_live": bool(otaku.get("nebius_configured")),
                "evidence_mode": otaku.get("evidence_mode"),
            },
        }

    # ---------------------------------------------------------------- proxy
    def proxy_target(self, path):
        for prefix in self.upstreams:
            if path == prefix.rstrip("/") or path.startswith(prefix):
                return prefix
        return None

    def proxy(self):
        prefix = self.proxy_target(urllib.parse.urlparse(self.path).path)
        if self.path == prefix.rstrip("/"):
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            self.send_header("Location", prefix)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        base = urllib.parse.urlparse(self.upstreams[prefix])
        rest = "/" + self.path[len(prefix):]
        if self.headers.get("Upgrade", "").lower() == "websocket":
            return self.tunnel(base, rest)
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1024 * 1024:
            return self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False})
        data = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("connection", "keep-alive", "transfer-encoding",
                                        "upgrade", "accept-encoding", "content-length")}
        req = urllib.request.Request(base.geturl().rstrip("/") + rest, data=data,
                                     method=self.command, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=60)  # noqa: S310 - fixed loopback upstream
        except urllib.error.HTTPError as err:
            resp = err
        except OSError:
            return self.send_json(HTTPStatus.BAD_GATEWAY, {
                "ok": False, "error": "upstream_unavailable",
                "message": f"The app behind {prefix} is not running. Start it with scripts/run.sh."})
        with resp:
            payload = resp.read()
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() not in ("connection", "keep-alive", "transfer-encoding",
                                     "content-length", "server", "date"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        return None

    def tunnel(self, base, rest):
        """Byte-level WebSocket relay; the Host header is kept as the public one."""
        try:
            up = socket.create_connection((base.hostname, base.port or 80), timeout=10)
        except OSError:
            return self.send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": "upstream_unavailable"})
        lines = [f"{self.command} {rest} {self.request_version}"]
        lines += [f"{k}: {v}" for k, v in self.headers.items()]
        up.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        up.settimeout(None)
        client = self.connection
        self.close_connection = True
        try:
            while True:
                ready, _, _ = select.select([client, up], [], [], 120)
                if not ready:
                    break
                for sock in ready:
                    chunk = sock.recv(65536)
                    if not chunk:
                        return None
                    (up if sock is client else client).sendall(chunk)
        except OSError:
            return None
        finally:
            up.close()
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Home Jarvis public showcase server")
    parser.add_argument("--host", default=os.environ.get("JARVIS_SHOWCASE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("JARVIS_SHOWCASE_PORT", "8780")))
    parser.add_argument("--ask-url", default=os.environ.get("ASK_THREE_URL", "http://127.0.0.1:8794"))
    parser.add_argument("--otaku-url", default=os.environ.get("OTAKU_URL", "http://127.0.0.1:8805"))
    parser.add_argument("--log-level", default=os.environ.get("JARVIS_SHOWCASE_LOG", "INFO"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s")
    Handler.upstreams = {"/ask-en/": args.ask_url.rstrip("/"), "/otaku-en/": args.otaku_url.rstrip("/")}
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        raise SystemExit(f"Cannot listen on {args.host}:{args.port}: {exc.strerror}. "
                         "Choose another port with --port or JARVIS_SHOWCASE_PORT.") from None
    server.daemon_threads = True
    log.info("Home Jarvis showcase on http://%s:%d/  (kiosk: /web/index.html)", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
