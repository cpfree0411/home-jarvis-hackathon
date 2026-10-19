"""HTTP/WebSocket application. Secure by default: loopback only, Host/Origin checked."""
from __future__ import annotations

import asyncio
import ipaddress
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__, ai, config, samples
from .domain import PANEL, presentation_reversed
from .repository import StoryRepository
from .speech import GeminiTranscribeLive

WEB = Path(__file__).resolve().parent / "web"
FONTS = {"Gaegu-Bold-latin.woff2", "Nunito-latin-var.woff2"}
NAMES = {"nemotron": "Nemotron", "gpt": "GPT", "claude": "Claude"}
MAX_TEXT = 6000
MIN_TEXT = 20


class NewStory(BaseModel):
    source: str = Field("text", pattern="^(voice|text|sample)$")
    sample_id: str | None = Field(None, max_length=40)


class StoryText(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT)


def _host_only(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value.split("]")[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.load()
    repo = StoryRepository(settings.db)
    networks = [ipaddress.ip_network(n, strict=False) for n in settings.allowed_clients]
    tasks: set[asyncio.Task] = set()
    listen_lock = asyncio.Lock()

    def spawn(coro):
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @asynccontextmanager
    async def lifespan(_app):
        repo.recover_inflight()
        yield
        for task in list(tasks):
            task.cancel()

    app = FastAPI(title="Ask the Three", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.repo = repo

    def client_allowed(host: str | None) -> bool:
        try:
            ip = ipaddress.ip_address(host or "")
        except ValueError:
            return False
        return any(ip in n for n in networks)

    def host_allowed(header: str | None) -> bool:
        return bool(header) and _host_only(header) in settings.allowed_hosts

    def ws_origins() -> list[str]:
        if not settings.ws_base:
            return []
        parts = urlsplit(settings.ws_base)
        return [f"{parts.scheme}://{parts.netloc}"]

    csp = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
           f"connect-src 'self' {' '.join(ws_origins())}; media-src 'none'; object-src 'none'; "
           f"base-uri 'none'; form-action 'none'; frame-ancestors {settings.frame_ancestors}")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not client_allowed(request.client.host if request.client else None):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        if not host_allowed(request.headers.get("host")):
            # Defeats DNS rebinding: a hostile page can't reach us under its own name.
            return JSONResponse({"detail": "unexpected host"}, status_code=421)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site", "")
            if origin is not None and origin not in settings.allowed_origins:
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
            if origin is None and site in ("cross-site", "same-site"):
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
            # JSON-only bodies force a CORS preflight that we never answer, so plain
            # HTML forms and no-cors fetches from other sites can't change state.
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"detail": "application/json required"}, status_code=415)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def seats_public() -> list[dict]:
        return [{"member": m, "name": NAMES[m], **ai.seat_identity(settings, m)} for m in PANEL]

    @app.get("/health")
    def health():
        # Provider/model identifiers only; never keys, prompts or provider responses.
        return {"ok": True, "version": __version__, "edition": "en",
                "organizer": {"provider": settings.organizer,
                              "model": settings.organizer_model if settings.organizer == "nebius" else "prepared-sample",
                              "endpoint": settings.nebius_base + "/chat/completions" if settings.organizer == "nebius" else None},
                "panel": [{"seat": s["member"], "provider": s["provider"], "model": s["model"], "live": s["live"],
                           **({"endpoint": settings.nebius_base + "/chat/completions", "thinking": False}
                              if s["provider"] == "nebius" else {})} for s in seats_public()],
                "stt": {"provider": settings.stt, "language": settings.stt_language,
                        **({"model": GeminiTranscribeLive.MODEL} if settings.stt != "off" else {})}}

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html", media_type="text/html")

    @app.get("/app.js")
    def script():
        return FileResponse(WEB / "app.js", media_type="application/javascript")

    @app.get("/style.css")
    def style():
        return FileResponse(WEB / "style.css", media_type="text/css")

    @app.get("/fonts/{name}")
    def font(name: str):
        if name not in FONTS:
            raise HTTPException(404)
        return FileResponse(WEB / "fonts" / name, media_type="font/woff2",
                            headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/api/config")
    def client_config():
        return {"seats": seats_public(),
                "organizer": "Nemotron" if settings.organizer == "nebius" else None,
                "stt": settings.stt != "off",
                "ws_base": settings.ws_base or None,
                "kiosk_lease": settings.kiosk_lease or None,
                "samples": samples.public_list(),
                "limits": {"min_text": MIN_TEXT, "max_text": MAX_TEXT}}

    def story_or_404(sid: str) -> dict:
        try:
            return repo.row(sid)
        except KeyError:
            raise HTTPException(404, "story unavailable") from None

    def busy_guard():
        if repo.inflight() >= settings.max_inflight:
            raise HTTPException(429, "busy")

    @app.post("/api/stories")
    def create_story(body: NewStory):
        if body.source == "sample" and body.sample_id not in samples.BY_ID:
            raise HTTPException(422, "unknown sample")
        if body.source == "voice" and settings.stt == "off":
            raise HTTPException(409, "speech input is not configured")
        return {"id": repo.create(body.source, body.sample_id if body.source == "sample" else None)}

    @app.get("/api/stories")
    def archive():
        return {"stories": repo.archive()}

    @app.get("/api/stories/{sid}")
    def get_story(sid: str):
        row = story_or_404(sid)
        data = {k: row[k] for k in ("id", "created_at", "status", "title", "source", "organizer", "error")}
        if row["status"] in ("REVIEW", "WAITING", "REVEALED"):
            data["organized"] = json.loads(row["organizer_output"])
        if row["status"] in ("WAITING", "REVEALED"):
            data["panel"] = repo.panel(sid)
        return data

    @app.get("/api/stories/{sid}/transcript")
    def transcript(sid: str):
        row = story_or_404(sid)
        if row["status"] not in ("REVIEW", "WAITING", "REVEALED"):
            raise HTTPException(409)
        return {"text": row["raw_transcript"]}

    async def organize_background(sid: str, text: str, sample_id: str | None):
        try:
            value, label = await asyncio.to_thread(ai.organize_story, settings, text, sample_id)
            repo.set_organized(sid, value, label)
        except Exception as exc:
            repo.fail_story(sid, getattr(exc, "code", "organizer_failed"))

    def accept_text(sid: str, text: str):
        row = story_or_404(sid)
        if row["status"] != "DRAFT":
            raise HTTPException(409)
        text = text.strip()
        if len(text) < MIN_TEXT:
            raise HTTPException(422, "too short")
        busy_guard()
        repo.set_transcript(sid, text[:MAX_TEXT])
        spawn(organize_background(sid, text[:MAX_TEXT], row["sample_id"]))

    @app.post("/api/stories/{sid}/text")
    async def submit_text(sid: str, body: StoryText):
        accept_text(sid, body.text)
        return {"status": "ORGANIZING"}

    @app.websocket("/ws/transcribe/{sid}")
    async def transcribe(websocket: WebSocket, sid: str):
        allowed = set(settings.allowed_origins)
        if (settings.stt == "off" or not client_allowed(websocket.client.host if websocket.client else None)
                or not host_allowed(websocket.headers.get("host"))
                or websocket.headers.get("origin") not in allowed):
            await websocket.close(code=1008)
            return
        try:
            if repo.row(sid)["status"] != "DRAFT":
                raise ValueError
        except (KeyError, ValueError):
            await websocket.close(code=1008)
            return
        if listen_lock.locked():
            await websocket.close(code=1013)
            return
        await websocket.accept()
        async with listen_lock:
            async def audio():
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        raise WebSocketDisconnect()
                    if msg.get("bytes") is not None:
                        yield msg["bytes"]
                    elif msg.get("text") == "stop":
                        break
            try:
                await websocket.send_json({"type": "ready"})
                async for event in GeminiTranscribeLive(settings.stt_language).stream(audio()):
                    await websocket.send_json(event)
                    if event["type"] == "complete":
                        try:
                            accept_text(sid, event["text"])
                        except HTTPException as exc:
                            code = "too_short" if exc.status_code == 422 else "busy" if exc.status_code == 429 else "state"
                            await websocket.send_json({"type": "error", "code": code})
                        break
            except WebSocketDisconnect:
                pass
            except Exception:
                try:
                    await websocket.send_json({"type": "error", "code": "speech_failed"})
                except Exception:
                    pass
            finally:
                try:
                    await websocket.close()
                except Exception:
                    pass

    async def run_panel(sid: str, approved: dict, sample_id: str | None):
        async def one(member: str):
            repo.panel_status(sid, member, "RUNNING")
            try:
                value = await asyncio.to_thread(ai.run_member, settings, member, approved,
                                                presentation_reversed(sid, member), sample_id, sid)
                repo.panel_status(sid, member, "COMPLETED", value)
            except Exception as exc:
                # A bounded category only; provider output may contain anything.
                repo.panel_status(sid, member, "FAILED", error=str(getattr(exc, "code", type(exc).__name__))[:40])
        await asyncio.gather(*(one(member) for member in PANEL))

    @app.post("/api/stories/{sid}/approve")
    async def approve(sid: str):
        row = story_or_404(sid)
        if row["status"] != "REVIEW":
            raise HTTPException(409)
        seats = {m: ai.seat_identity(settings, m) for m in PANEL}
        if any(s["live"] for s in seats.values()):
            if repo.live_runs_today() >= settings.daily_live_limit:
                raise HTTPException(429, "daily live limit reached")
        busy_guard()
        approved = json.loads(row["organizer_output"])
        # Snapshot exactly what all three receive; labels are positions, not people.
        repo.approve(sid, approved, seats, {m: presentation_reversed(sid, m) for m in PANEL})
        spawn(run_panel(sid, approved, row["sample_id"]))
        return {"status": "WAITING", "members": list(PANEL)}

    @app.delete("/api/stories/{sid}")
    def delete(sid: str):
        try:
            repo.soft_delete(sid)
        except KeyError:
            raise HTTPException(404) from None
        return {"deleted": True}

    return app
