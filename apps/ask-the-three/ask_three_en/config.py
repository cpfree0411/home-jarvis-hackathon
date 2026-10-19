"""Runtime configuration, read once from the process environment.

Everything is optional except NEBIUS_API_KEY for live Nemotron calls. Without
any key the app still runs: bundled sample stories use their prepared summaries
and every seat is an explicitly labelled demo fixture.
"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_NEMOTRON = "nvidia/Nemotron-3-Ultra-550b-a55b"
DEFAULT_NEBIUS_BASE = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_PORT = 8794
SEATS = ("nemotron", "gpt", "claude")
SEAT_PROVIDERS = {
    "nemotron": ("nebius", "fixture"),
    "gpt": ("openai", "codex-cli", "fixture"),
    "claude": ("anthropic", "claude-cli", "fixture"),
}


class ConfigError(ValueError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in _env(name, default).split(",") if p.strip()]


def default_state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "ask-three-en"


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    state_dir: Path = field(default_factory=default_state_dir)
    db_path: Path | None = None
    nebius_base: str = DEFAULT_NEBIUS_BASE
    nemotron_model: str = DEFAULT_NEMOTRON
    organizer_model: str = DEFAULT_NEMOTRON
    organizer: str = "nebius"
    seat_provider: dict = field(default_factory=dict)
    openai_model: str = ""
    openai_base: str = "https://api.openai.com/v1"
    anthropic_model: str = "claude-sonnet-5-5"
    codex_bin: str = "codex"
    codex_model: str = ""
    codex_auth: str = ""
    claude_bin: str = "claude"
    claude_model: str = "claude-sonnet-5-5"
    claude_credentials: str = ""
    stt: str = "off"
    stt_language: str = "en-US"
    allowed_clients: list = field(default_factory=list)
    allowed_hosts: list = field(default_factory=list)
    allowed_origins: list = field(default_factory=list)
    frame_ancestors: str = "'self'"
    ws_base: str = ""
    kiosk_lease: str = ""
    max_inflight: int = 2
    daily_live_limit: int = 60

    @property
    def db(self) -> Path:
        return self.db_path or self.state_dir / "stories.sqlite3"

    def live(self, seat: str) -> bool:
        return self.seat_provider[seat] != "fixture"


def nebius_key_present() -> bool:
    return bool(_env("NEBIUS_API_KEY"))


def load() -> Settings:
    s = Settings()
    s.host = _env("ASK_THREE_HOST", "127.0.0.1")
    try:
        s.port = int(_env("ASK_THREE_PORT", str(DEFAULT_PORT)))
        s.max_inflight = max(1, int(_env("ASK_THREE_MAX_INFLIGHT", "2")))
        s.daily_live_limit = max(0, int(_env("ASK_THREE_DAILY_LIVE_LIMIT", "60")))
    except ValueError as exc:
        raise ConfigError("ASK_THREE_PORT / ASK_THREE_MAX_INFLIGHT / ASK_THREE_DAILY_LIVE_LIMIT must be integers") from exc
    if _env("ASK_THREE_STATE"):
        s.state_dir = Path(_env("ASK_THREE_STATE")).expanduser()
    if _env("ASK_THREE_DB"):
        s.db_path = Path(_env("ASK_THREE_DB")).expanduser()
    s.nebius_base = _env("NEBIUS_BASE_URL", DEFAULT_NEBIUS_BASE).rstrip("/")
    s.nemotron_model = _env("ASK_THREE_NEMOTRON_MODEL", DEFAULT_NEMOTRON)
    s.organizer_model = _env("ASK_THREE_ORGANIZER_MODEL", s.nemotron_model)
    has_nebius = nebius_key_present()
    s.organizer = _env("ASK_THREE_ORGANIZER", "nebius" if has_nebius else "fixture")
    defaults = {
        "nemotron": "nebius" if has_nebius else "fixture",
        "gpt": "openai" if _env("OPENAI_API_KEY") else "fixture",
        "claude": "anthropic" if _env("ANTHROPIC_API_KEY") else "fixture",
    }
    for seat in SEATS:
        value = _env(f"ASK_THREE_SEAT_{seat.upper()}", defaults[seat])
        if value not in SEAT_PROVIDERS[seat]:
            raise ConfigError(f"ASK_THREE_SEAT_{seat.upper()} must be one of {', '.join(SEAT_PROVIDERS[seat])}")
        s.seat_provider[seat] = value
    if s.organizer not in ("nebius", "fixture"):
        raise ConfigError("ASK_THREE_ORGANIZER must be nebius or fixture")
    s.openai_model = _env("ASK_THREE_OPENAI_MODEL")
    s.openai_base = _env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    s.anthropic_model = _env("ASK_THREE_ANTHROPIC_MODEL", "claude-sonnet-5-5")
    s.codex_bin = _env("ASK_THREE_CODEX_BIN", "codex")
    s.codex_model = _env("ASK_THREE_CODEX_MODEL")
    s.codex_auth = _env("ASK_THREE_CODEX_AUTH")
    s.claude_bin = _env("ASK_THREE_CLAUDE_BIN", "claude")
    s.claude_model = _env("ASK_THREE_CLAUDE_MODEL", "claude-sonnet-5-5")
    s.claude_credentials = _env("ASK_THREE_CLAUDE_CREDENTIALS")
    if s.seat_provider["gpt"] == "openai" and not s.openai_model:
        raise ConfigError("ASK_THREE_OPENAI_MODEL is required when the GPT seat uses the OpenAI API")
    if s.seat_provider["gpt"] == "codex-cli" and not s.codex_model:
        raise ConfigError("ASK_THREE_CODEX_MODEL is required when the GPT seat uses the Codex CLI")
    s.stt = _env("ASK_THREE_STT", "gemini-live" if _env("GEMINI_API_KEY") else "off")
    if s.stt not in ("gemini-live", "off"):
        raise ConfigError("ASK_THREE_STT must be gemini-live or off")
    s.stt_language = _env("ASK_THREE_STT_LANGUAGE", "en-US")
    s.allowed_clients = _list("ASK_THREE_ALLOWED_CLIENTS", "127.0.0.1/32,::1/128")
    for net in s.allowed_clients:
        try:
            ipaddress.ip_network(net, strict=False)
        except ValueError as exc:
            raise ConfigError(f"ASK_THREE_ALLOWED_CLIENTS entry is not an IP or CIDR: {net}") from exc
    s.allowed_hosts = [h.lower() for h in _list("ASK_THREE_ALLOWED_HOSTS", "127.0.0.1,localhost,[::1]")]
    s.allowed_origins = _list("ASK_THREE_ALLOWED_ORIGINS",
                              f"http://127.0.0.1:{s.port},http://localhost:{s.port}")
    s.frame_ancestors = _env("ASK_THREE_FRAME_ANCESTORS", "'self'")
    s.ws_base = _env("ASK_THREE_WS_BASE")
    s.kiosk_lease = _env("ASK_THREE_KIOSK_LEASE_URL")
    return s
