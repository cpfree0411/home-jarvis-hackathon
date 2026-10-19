"""The English edition is English all the way down, and the repository is safe to publish."""
import re
import subprocess
from pathlib import Path

import pytest

from ask_three_en import ai, config
from ask_three_en.samples import SAMPLES

ROOT = Path(__file__).resolve().parents[1]
HANGUL = re.compile("[%s-%s%s-%s%s-%s]" % tuple(map(chr, (0x1100, 0x11FF, 0x3130, 0x318F, 0xAC00, 0xD7AF))))
# Assembled at runtime so this file doesn't contain the literal patterns it forbids.
FORBIDDEN = [
    re.compile("/" + "home" + "/" + r"[a-z]"),
    re.compile(r"192\.168\." + r"\d"),
    re.compile(r"10\.\d+\.\d+\." + r"\d"),
    re.compile("nev" + "ius"),
    re.compile(r"(sk|nb|key)-[A-Za-z0-9]{24,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\."),
    re.compile("BEGIN [A-Z ]*PRIVATE" + " KEY"),
    re.compile("jarvis-" + "pi|ssh " + "jp"),
]


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout.split("\n")
        return [ROOT / p for p in out if p]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts]


TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".toml", ".txt", ".example", ".service", ".sh", ".json", ".template", ""}


def text_files():
    return [p for p in tracked_files() if p.suffix in TEXT_SUFFIXES and p.is_file()
            and "screenshots" not in p.parts]


def test_no_korean_anywhere_in_shipped_text():
    offenders = [str(p.relative_to(ROOT)) for p in text_files() if HANGUL.search(p.read_text(errors="ignore"))]
    assert offenders == []


def test_no_private_paths_addresses_or_secrets():
    offenders = []
    for path in text_files():
        text = path.read_text(errors="ignore")
        for pattern in FORBIDDEN:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(ROOT)}: {pattern.pattern}")
    assert offenders == []


def test_no_forbidden_file_types():
    bad = [p for p in tracked_files() if p.suffix in {".sqlite3", ".db", ".wav", ".flac", ".mp3", ".log", ".pem", ".key"}
           or p.name == ".env"]
    assert bad == []


def test_prompts_require_english_output():
    assert "plain-English" in ai.PANEL_RULES and "Write every field in natural, plain English" in ai.ORGANIZER_RULES
    for sample in SAMPLES:
        for text in (sample["text"], str(sample["organized"]), str(sample["fixture"])):
            assert text.isascii() or not HANGUL.search(text)


def test_secure_defaults():
    s = config.load()
    assert s.host == "127.0.0.1" and s.port == 8794
    assert s.allowed_clients == ["127.0.0.1/32", "::1/128"]
    assert s.nemotron_model == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert s.seat_provider == {"nemotron": "fixture", "gpt": "fixture", "claude": "fixture"}


def test_config_validation(monkeypatch):
    monkeypatch.setenv("ASK_THREE_SEAT_GPT", "openai")
    with pytest.raises(config.ConfigError):
        config.load()
    monkeypatch.setenv("ASK_THREE_OPENAI_MODEL", "gpt-x")
    assert config.load().seat_provider["gpt"] == "openai"
    monkeypatch.setenv("ASK_THREE_SEAT_NEMOTRON", "openai")
    with pytest.raises(config.ConfigError):
        config.load()
    monkeypatch.delenv("ASK_THREE_SEAT_NEMOTRON")
    monkeypatch.setenv("ASK_THREE_ALLOWED_CLIENTS", "not-an-ip")
    with pytest.raises(config.ConfigError):
        config.load()


def test_env_file_never_overrides_and_never_prints(tmp_path, monkeypatch, capsys):
    from ask_three_en import cli
    env = tmp_path / ".env"
    env.write_text("NEBIUS_API_KEY=nb-from-file\nASK_THREE_PORT=9999\n# comment\n")
    env.chmod(0o600)
    monkeypatch.setenv("ASK_THREE_PORT", "8794")
    assert cli.main(["check", "--env-file", str(env)]) == 0
    out = capsys.readouterr().out
    assert "nb-from-file" not in out and "NEBIUS_API_KEY set" in out and ":8794/" in out
