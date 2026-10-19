"""Dependency-free HTTP server: static kiosk UI, gallery manifest and the Research Guide API.

Routes
  GET  /health                      liveness + non-secret capability flags
  GET  /                            kiosk UI (relative asset URLs, so it works under any path prefix)
  GET  /api/config  /api/gallery    UI configuration and artwork metadata
  GET  /art/<file>  /media/<file>   only files listed in a validated manifest
  POST /api/research                {"item_id","topic_id"} or {"query"}  -> session view
  GET  /api/research/<id>           poll a session
  POST /api/research/<id>/cancel    cancel a running session
"""
import json
import logging
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .errors import ApiError, ResearchError, message_for
from .nebius import MODEL

logger = logging.getLogger("otaku-gallery.http")

MAX_BODY = 4096
STATIC_RE = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9._-]{0,60}\.(?:css|js|svg|html|ico|webmanifest))$")
SESSION_RE = re.compile(r"^/api/research/([A-Za-z0-9_-]{8,40})(/cancel)?$")
MIME = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".html": "text/html; charset=utf-8",
        ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp", ".webmanifest": "application/manifest+json"}


class App:
    def __init__(self, config, gallery, manager, writer, web_dir):
        self.config, self.gallery, self.manager, self.writer = config, gallery, manager, writer
        self.web_dir = Path(web_dir).resolve()
        self.extra_origins = {o.strip().rstrip("/") for o in
                              os.environ.get("OTAKU_ALLOWED_ORIGINS", "").split(",") if o.strip()}
        self.frame_ancestors = os.environ.get("OTAKU_FRAME_ANCESTORS", "'self'")

    def health(self):
        return {"ok": True, "app": "otaku-gallery-en", "version": __version__,
                "artworks": len(self.gallery.items), "research_enabled": self.config.research_enabled,
                "nebius_configured": self.writer.configured(), "model": MODEL,
                "evidence_mode": self.config.evidence_mode}

    def public_config(self):
        return {"ok": True, "model": MODEL, "provider": "Nebius Token Factory",
                "research_enabled": self.config.research_enabled,
                "nebius_configured": self.writer.configured(), "evidence_mode": self.config.evidence_mode,
                "query_max": 80}

    def start_research(self, body):
        if not isinstance(body, dict):
            raise ApiError(400, "bad_request")
        query, context = "", None
        if body.get("item_id") is not None or body.get("topic_id") is not None:
            item = self.gallery.get(body.get("item_id")) if isinstance(body.get("item_id"), str) else None
            if not item:
                raise ApiError(404, "unknown_artwork")
            topic = next((t for t in item["topics"] if t["id"] == body.get("topic_id")), None)
            if not topic:
                raise ApiError(404, "unknown_topic")
            query = topic["query"]
            context = {"item_id": item["id"], "title": item["title"], "topic": topic["label"]}
        elif isinstance(body.get("query"), str):
            query = body["query"]
        else:
            raise ApiError(400, "bad_request")
        try:
            return self.manager.start(query, context=context, request_id=str(body.get("request_id") or ""),
                                      refresh=bool(body.get("refresh")))
        except ResearchError as exc:
            raise ApiError(503 if exc.code == "research_disabled" else 400, exc.code, message_for(exc.code))


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OtakuGalleryEN/" + __version__
        protocol_version = "HTTP/1.1"

        # ---- plumbing
        def log_message(self, fmt, *args):
            logger.info("%s %s", self.command, urlsplit(self.path).path[:120])

        def _send(self, status, body, content_type, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", (
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors "
                + app.frame_ancestors))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, payload):
            self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                       {"Cache-Control": "no-store"})

        def _error(self, exc):
            self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})

        def _file(self, path, cacheable=True):
            try:
                data = path.read_bytes()
            except OSError:
                raise ApiError(404, "not_found")
            ctype = MIME.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            extra = {"Cache-Control": "public, max-age=300" if cacheable else "no-cache"}
            if path.suffix.lower() == ".svg":  # SVG is an image here, never a script host
                extra["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
            self._send(200, data, ctype, extra)

        def _check_origin(self):
            origin = self.headers.get("Origin")
            if not origin:
                return
            parsed = urlsplit(origin)
            host = parsed.netloc.lower()
            allowed = {(self.headers.get("Host") or "").lower()}
            if (parsed.scheme not in ("http", "https") or not host or parsed.username
                    or (host not in allowed and origin.rstrip("/") not in app.extra_origins)):
                raise ApiError(403, "forbidden_origin")

        def _read_json(self):
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                raise ApiError(415, "unsupported_media_type")
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                raise ApiError(400, "bad_request")
            if length < 0 or length > MAX_BODY:
                raise ApiError(413, "payload_too_large")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ApiError(400, "bad_json")

        # ---- routing
        def _route(self, method):
            path = urlsplit(self.path).path
            if method in ("GET", "HEAD"):
                if path == "/health":
                    return self._json(200, app.health())
                if path in ("/", "/index.html"):
                    return self._file(app.web_dir / "index.html", cacheable=False)
                if path == "/api/config":
                    return self._json(200, app.public_config())
                if path == "/api/gallery":
                    return self._json(200, {"ok": True, "items": app.gallery.public()})
                m = re.match(r"^/(art|media)/([A-Za-z0-9][A-Za-z0-9._-]{0,100})$", path)
                if m:
                    found = app.gallery.path_for("bundled" if m.group(1) == "art" else "local", m.group(2))
                    if not found:
                        raise ApiError(404, "not_found")
                    return self._file(found)
                m = SESSION_RE.match(path)
                if m and not m.group(2):
                    view = app.manager.get(m.group(1))
                    if view is None:
                        raise ApiError(404, "session_not_found")
                    return self._json(200, view)
                m = STATIC_RE.match(path)
                if m:
                    target = (app.web_dir / m.group(1)).resolve()
                    if target.parent == app.web_dir and target.is_file():
                        return self._file(target, cacheable=False)
                raise ApiError(404, "not_found")
            if method == "POST" or method == "DELETE":
                self._check_origin()
                if path == "/api/research" and method == "POST":
                    return self._json(200, app.start_research(self._read_json()))
                m = SESSION_RE.match(path)
                if m and ((m.group(2) and method == "POST") or (not m.group(2) and method == "DELETE")):
                    if method == "POST":
                        self._read_json()
                    view = app.manager.cancel(m.group(1))
                    if view is None:
                        raise ApiError(404, "session_not_found")
                    return self._json(200, view)
                raise ApiError(404, "not_found")
            raise ApiError(405, "method_not_allowed")

        def _dispatch(self, method):
            try:
                self._route(method)
            except ApiError as exc:
                self._error(exc)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:  # noqa: BLE001
                logger.exception("request_failed")
                self._error(ApiError(500, "internal_error"))

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_PUT(self):
            self._dispatch("PUT")

        do_PATCH = do_PUT
    return Handler


def make_server(app, host, port):
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server


def serve_in_thread(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="http")
    thread.start()
    return thread
