"""Environment-driven configuration. Secrets are read from the process environment only."""
import os
import re
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

def asset_root():
    checkout = Path(__file__).resolve().parent.parent
    candidates = [checkout, Path(sys.prefix) / "share" / "otaku-gallery-en",
                  Path(sysconfig.get_path("data", scheme=sysconfig.get_preferred_scheme("user")))
                  / "share" / "otaku-gallery-en"]
    return next((p for p in candidates if (p / "web" / "index.html").is_file()
                 and (p / "data" / "gallery.json").is_file()), checkout)


ROOT = asset_root()


def load_dotenv(path):
    """Parse simple KEY=VALUE lines into os.environ without overriding real variables.
    The file is data, never sourced or evaluated."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if not m or line.lstrip().startswith("#"):
            continue
        value = m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(m.group(1), value)


def _flag(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "off", "false", "no", ""}


def _int(name, default, low, high):
    try:
        return max(low, min(high, int(os.environ.get(name, default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    research_enabled: bool
    evidence_mode: str      # live | fixture | auto
    rate_max_runs: int
    cache_ttl: int
    root: Path
    local_manifest: Path

    @classmethod
    def from_env(cls):
        mode = os.environ.get("OTAKU_EVIDENCE_MODE", "auto").strip().lower()
        return cls(
            host=os.environ.get("OTAKU_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_int("OTAKU_PORT", 8805, 1, 65535),
            research_enabled=_flag("OTAKU_RESEARCH", True),
            evidence_mode=mode if mode in ("live", "fixture", "auto") else "auto",
            rate_max_runs=_int("OTAKU_RATE_MAX_RUNS", 10, 1, 100),
            cache_ttl=_int("OTAKU_CACHE_TTL", 600, 0, 86400),
            root=ROOT,
            local_manifest=Path(os.environ.get("OTAKU_LOCAL_MANIFEST", str(Path.cwd() / "media" / "gallery.json"))),
        )
