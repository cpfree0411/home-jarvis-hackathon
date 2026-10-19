import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ask_three_en import ai, config
from ask_three_en.app import create_app
from ask_three_en.domain import PANEL, presentation_reversed
from ask_three_en.samples import BY_ID

BASE = "http://127.0.0.1:8794"
ORIGIN = {"Origin": BASE}
RESULT = {"choice": "A", "strength": "LEAN", "reasoning": "A is a little more convincing as described.",
          "other_side_credit": "B has a fair point too.", "suggestion": "Agree on a shared rule."}


def make(tmp_path, **env):
    settings = config.load()
    settings.db_path = tmp_path / "stories.sqlite3"
    for key, value in env.items():
        setattr(settings, key, value)
    app = create_app(settings)
    return app, TestClient(app, base_url=BASE, client=("127.0.0.1", 50000))


def wait_for(client, sid, status, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/stories/{sid}").json()
        if data["status"] == status:
            return data
        time.sleep(0.05)
    raise AssertionError(f"story never reached {status}: {data}")


def test_api_never_leaks_partial_panel(tmp_path):
    app, client = make(tmp_path)
    repo = app.state.repo
    organized = BY_ID["haircut"]["organized"]
    sid = repo.create("text")
    repo.set_transcript(sid, "A long and specific synthetic account for the test.")
    repo.set_organized(sid, organized, "test")
    seats = {m: {"provider": "nebius", "model": "m", "live": True} for m in PANEL}
    repo.approve(sid, organized, seats, {m: presentation_reversed(sid, m) for m in PANEL})
    for i, m in enumerate(PANEL):
        repo.panel_status(sid, m, "RUNNING")
        repo.panel_status(sid, m, "COMPLETED", RESULT)
        data = client.get(f"/api/stories/{sid}").json()
        if i < 2:
            assert data["panel"] == {"status": "WAITING", "members": list(PANEL)}
            assert "choice" not in json.dumps(data) and "reasoning" not in json.dumps(data)
        else:
            assert data["panel"]["status"] == "REVEALED"
            assert all(r["choice"] == "A" and r["live"] for r in data["panel"]["members"].values())


def test_sample_flow_without_any_key_is_fully_labelled_demo(tmp_path):
    app, client = make(tmp_path)
    with client:
        cfg = client.get("/api/config").json()
        assert [s["live"] for s in cfg["seats"]] == [False, False, False]
        assert cfg["organizer"] is None and cfg["stt"] is False
        sample = BY_ID["haircut"]
        sid = client.post("/api/stories", json={"source": "sample", "sample_id": "haircut"}, headers=ORIGIN).json()["id"]
        assert client.post(f"/api/stories/{sid}/text", json={"text": sample["text"]}, headers=ORIGIN).status_code == 200
        review = wait_for(client, sid, "REVIEW")
        assert review["organizer"] == "prepared-sample"
        assert review["organized"]["title"] == sample["organized"]["title"]
        assert client.post(f"/api/stories/{sid}/approve", json={}, headers=ORIGIN).json()["status"] == "WAITING"
        done = wait_for(client, sid, "REVEALED")
        members = done["panel"]["members"]
        assert {m: r["live"] for m, r in members.items()} == {m: False for m in PANEL}
        assert all(r["provider"] == "fixture" and r["model"] == "demo-fixture" for r in members.values())
        assert done["panel"]["aggregate"]["live_votes"] == 0
        archive = client.get("/api/stories").json()["stories"]
        assert archive[0]["id"] == sid and archive[0]["live"] == {m: False for m in PANEL}
        assert client.get(f"/api/stories/{sid}/transcript").json()["text"] == sample["text"]
        assert client.request("DELETE", f"/api/stories/{sid}", headers={**ORIGIN, "Content-Type": "application/json"}).json() == {"deleted": True}
        assert client.get("/api/stories").json()["stories"] == []


def test_custom_story_without_nebius_key_fails_honestly(tmp_path):
    app, client = make(tmp_path)
    with client:
        sid = client.post("/api/stories", json={"source": "text"}, headers=ORIGIN).json()["id"]
        client.post(f"/api/stories/{sid}/text", json={"text": "My roommate and I disagree about the thermostat setting."},
                    headers=ORIGIN)
        failed = wait_for(client, sid, "FAILED")
        assert failed["error"] == "organizer_not_configured"


def test_live_seat_mix_and_archive_order(tmp_path, monkeypatch):
    app, client = make(tmp_path, organizer="nebius")
    app.state.settings.seat_provider.update({"nemotron": "nebius"})
    organized = BY_ID["dinner-bill"]["organized"]
    monkeypatch.setattr(ai, "organize_story", lambda s, text, sample_id=None: (dict(organized), "nvidia/test"))
    real = ai.run_member

    def fake(settings, member, approved, reversed_order, sample_id=None, story_id=""):
        if member == "nemotron":
            return dict(RESULT)
        return real(settings, member, approved, reversed_order, sample_id, story_id)
    monkeypatch.setattr(ai, "run_member", fake)
    ids = []
    with client:
        for _ in range(2):
            sid = client.post("/api/stories", json={"source": "text"}, headers=ORIGIN).json()["id"]
            client.post(f"/api/stories/{sid}/text", json={"text": "Four friends disagree about splitting a bill."}, headers=ORIGIN)
            wait_for(client, sid, "REVIEW")
            client.post(f"/api/stories/{sid}/approve", json={}, headers=ORIGIN)
            ids.append(sid)
            done = wait_for(client, sid, "REVEALED")
            assert done["panel"]["members"]["nemotron"]["live"] is True
            assert done["panel"]["members"]["gpt"]["live"] is False
            assert "Demo placeholder" in done["panel"]["members"]["gpt"]["reasoning"]
            time.sleep(0.01)
        assert [s["id"] for s in client.get("/api/stories").json()["stories"]] == ids[::-1]


def test_security_defaults(tmp_path):
    app, client = make(tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'self'" in csp and "unsafe-inline" not in csp
    assert page.headers["x-content-type-options"] == "nosniff"
    # DNS rebinding: unknown Host header
    assert client.get("/api/config", headers={"Host": "attacker.example"}).status_code == 421
    # Cross-site writes are refused even from an allowed client address.
    assert client.post("/api/stories", json={"source": "text"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/stories", json={"source": "text"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/stories", content="source=text", headers={
        "Origin": BASE, "Content-Type": "application/x-www-form-urlencoded"}).status_code == 415
    # Voice is unavailable unless speech is configured.
    assert client.post("/api/stories", json={"source": "voice"}, headers=ORIGIN).status_code == 409
    assert client.post("/api/stories", json={"source": "sample", "sample_id": "nope"}, headers=ORIGIN).status_code == 422
    assert client.get("/fonts/../app.py").status_code == 404
    assert client.get("/fonts/Gaegu-Bold-latin.woff2").status_code == 200
    other = TestClient(app, base_url=BASE, client=("192.0.2.10", 50000))
    assert other.get("/health").status_code == 403


def test_websocket_requires_configured_speech_and_origin(tmp_path):
    app, client = make(tmp_path, stt="gemini-live")
    sid = app.state.repo.create("voice")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/transcribe/{sid}", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_json()
    app2, client2 = make(tmp_path / "off")
    with pytest.raises(WebSocketDisconnect):
        with client2.websocket_connect(f"/ws/transcribe/{sid}", headers=ORIGIN) as ws:
            ws.receive_json()


def test_health_exposes_models_not_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-test-not-a-real-key")
    app, client = make(tmp_path)
    app.state.settings.seat_provider["nemotron"] = "nebius"
    body = client.get("/health").text
    assert "sk-test" not in body and "nvidia/Nemotron-3-Ultra-550b-a55b" in body
    data = json.loads(body)
    assert data["panel"][0] == {"seat": "nemotron", "provider": "nebius", "model": "nvidia/Nemotron-3-Ultra-550b-a55b",
                                "live": True, "endpoint": "https://api.tokenfactory.nebius.com/v1/chat/completions",
                                "thinking": False}


def test_busy_and_daily_limits(tmp_path):
    app, client = make(tmp_path, max_inflight=1, daily_live_limit=0)
    app.state.settings.seat_provider["nemotron"] = "nebius"
    repo = app.state.repo
    sid = repo.create("text")
    repo.set_transcript(sid, "A synthetic story that is long enough.")
    repo.set_organized(sid, BY_ID["haircut"]["organized"], "test")
    assert client.post(f"/api/stories/{sid}/approve", json={}, headers=ORIGIN).status_code == 429
    other = repo.create("text")
    repo.set_transcript(other, "Another synthetic story, still organizing.")
    sid2 = client.post("/api/stories", json={"source": "text"}, headers=ORIGIN).json()["id"]
    assert client.post(f"/api/stories/{sid2}/text", json={"text": "x" * 40}, headers=ORIGIN).status_code == 429


def test_restart_recovery_reveals_interrupted_panel(tmp_path):
    app, _ = make(tmp_path)
    repo = app.state.repo
    sid = repo.create("text")
    repo.set_transcript(sid, "A synthetic story that is long enough.")
    repo.set_organized(sid, BY_ID["haircut"]["organized"], "test")
    seats = {m: {"provider": "fixture", "model": "demo-fixture", "live": False} for m in PANEL}
    repo.approve(sid, BY_ID["haircut"]["organized"], seats, {m: False for m in PANEL})
    repo.panel_status(sid, "nemotron", "RUNNING")
    repo.panel_status(sid, "nemotron", "COMPLETED", RESULT)
    repo.recover_inflight()
    panel = repo.panel(sid)
    assert panel["status"] == "REVEALED"
    assert panel["members"]["gpt"]["error"] == "service_restarted"
