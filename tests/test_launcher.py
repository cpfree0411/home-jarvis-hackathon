"""Launcher environment rules: demo mode can never reach a paid provider."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run_showcase", REPO / "scripts" / "run_showcase.py")
run_showcase = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_showcase)


def args(tmp_path, **kw):
    base = dict(demo=False, env_file=None, host="127.0.0.1", port=8780, ask_port=8794,
                otaku_port=8805, state_dir=tmp_path / "state")
    base.update(kw)
    return argparse.Namespace(**base)


def test_env_file_parsing(tmp_path):
    f = tmp_path / "keys.env"
    f.write_text("# comment\nexport NEBIUS_API_KEY='abc'\nOTHER = \"x y\"\nnot a line\n\nEMPTY=\n")
    assert run_showcase.read_env_file(f) == {"NEBIUS_API_KEY": "abc", "OTHER": "x y", "EMPTY": ""}


def test_live_mode_passes_key_to_apps_only(tmp_path):
    f = tmp_path / "keys.env"
    f.write_text("NEBIUS_API_KEY=k1\nOPENAI_API_KEY=k2\n")
    kiosk, ask, otaku = run_showcase.build_envs(args(tmp_path, env_file=f), {"PATH": "/bin"})
    assert ask["NEBIUS_API_KEY"] == "k1" and ask["OPENAI_API_KEY"] == "k2"
    assert otaku["NEBIUS_API_KEY"] == "k1" and "OPENAI_API_KEY" not in otaku
    assert "NEBIUS_API_KEY" not in kiosk and "OPENAI_API_KEY" not in kiosk
    assert "http://127.0.0.1:8780" in ask["ASK_THREE_ALLOWED_ORIGINS"].split(",")
    assert otaku["OTAKU_LOCAL_MANIFEST"].endswith("no-local-gallery.json")


def test_process_environment_wins_over_env_file(tmp_path):
    f = tmp_path / "keys.env"
    f.write_text("NEBIUS_API_KEY=from-file\n")
    _, ask, _ = run_showcase.build_envs(args(tmp_path, env_file=f), {"NEBIUS_API_KEY": "from-env"})
    assert ask["NEBIUS_API_KEY"] == "from-env"


def test_demo_mode_strips_every_provider_key(tmp_path):
    f = tmp_path / "keys.env"
    f.write_text("NEBIUS_API_KEY=k1\n")
    environ = {"NEBIUS_API_KEY": "x", "ANTHROPIC_API_KEY": "y", "GEMINI_API_KEY": "z",
               "ASK_THREE_SEAT_GPT": "codex-cli", "ASK_THREE_ORGANIZER": "nebius"}
    kiosk, ask, otaku = run_showcase.build_envs(args(tmp_path, demo=True, env_file=f), environ)
    for env in (kiosk, ask, otaku):
        assert not any(k in env for k in run_showcase.PROVIDER_KEYS)
    assert ask["ASK_THREE_ORGANIZER"] == "fixture"
    assert {ask[f"ASK_THREE_SEAT_{s}"] for s in ("NEMOTRON", "GPT", "CLAUDE")} == {"fixture"}


def test_missing_env_file_is_an_error(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        run_showcase.build_envs(args(tmp_path, env_file=tmp_path / "nope.env"), {})


def test_port_check_refuses_a_live_listener_only():
    import socket
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert run_showcase.port_free("127.0.0.1", port) is False
    assert run_showcase.port_free("127.0.0.1", port) is True
