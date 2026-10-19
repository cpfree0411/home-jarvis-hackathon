import os

import pytest

PROVIDER_ENV = ("NEBIUS_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Tests never see a real key or the developer's state directory."""
    for name in list(os.environ):
        if name.startswith("ASK_THREE_") or name in PROVIDER_ENV:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ASK_THREE_STATE", str(tmp_path / "state"))
    yield
