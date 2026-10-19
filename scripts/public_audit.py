#!/usr/bin/env python3
"""Public-release audit for this repository.

Scans every file Git would publish (tracked plus untracked-but-not-ignored)
and, with --history, every blob reachable from any ref. Fails on:

  * secret-shaped values (API keys, bearer tokens, private keys, bot tokens)
  * household identifiers (private addresses, home paths, hostnames, emails)
  * files that must never be published (.env, databases, keys, venvs, logs)
  * Hangul in the public kiosk and documentation (the household UI is Korean;
    this build must be the English one)
  * PNG text metadata, oversized files

Usage: python scripts/public_audit.py [--history] [--json]
       AUDIT_PRIVATE_TERMS=/path/outside/repo/terms.txt python scripts/public_audit.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAX_BYTES = 5 * 1024 * 1024

SECRETS = {
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "google_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "telegram_bot_token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "bearer_literal": re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}"),
    "key_assignment": re.compile(
        r"(?i)\b[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*['\"]?([A-Za-z0-9_\-./+]{16,})"),
}
PRIVATE = {
    "private_ipv4": re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    "home_path": re.compile(r"/home/[a-z][a-z0-9_-]*/|/Users/[A-Za-z]|C:\\\\Users\\\\"),
    "tailnet_host": re.compile(r"\.ts\.net\b", re.I),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@(?:gmail|naver|daum|kakao|hanmail|outlook|icloud)\.[a-z.]+\b", re.I),
    "chat_id": re.compile(r"(?i)chat_id\s*[=:]\s*-?\d{6,}"),
}
HANGUL = re.compile("[%s-%s]" % (chr(0xAC00), chr(0xD7A3)))
# Hangul is only tolerated where an app *tests that it is absent*, or in a
# Wikipedia-derived snapshot that quotes a native-language title.
HANGUL_OK = re.compile(r"^apps/[^/]+/(tests|scripts)/|^apps/otaku-gallery/data/fixtures/")
FORBIDDEN_NAME = re.compile(
    r"(^|/)(\.env(\.[^/]*)?|id_rsa[^/]*|id_ed25519[^/]*|[^/]*\.(pem|key|p12|sqlite3?|db|log)|"
    r"credentials[^/]*\.json|token[^/]*\.json|\.venv|node_modules|\.state)(/|$)")
ALLOWED_FORBIDDEN = {".env.example"}
# Values in these files are documented placeholders, not secrets.
PLACEHOLDER_OK = re.compile(r"^zz-test-|your[-_ ]?key|<[^>]+>|\.\.\.|x{6,}|example|placeholder|changeme|REDACTED", re.I)


def private_terms() -> re.Pattern | None:
    """Household names, account handles, etc. live OUTSIDE the repo.

    Point AUDIT_PRIVATE_TERMS at a file with one term per line; the terms are
    matched case-insensitively and never printed in full.
    """
    path = os.environ.get("AUDIT_PRIVATE_TERMS")
    if not path:
        return None
    terms = [t.strip() for t in Path(path).read_text(encoding="utf-8").splitlines()
             if t.strip() and not t.startswith("#")]
    return re.compile("|".join(re.escape(t) for t in terms), re.I) if terms else None


TERMS = private_terms()
# If real provider keys are loaded in this shell, their exact values must not
# appear anywhere (checked, never printed).
KEY_VALUES = [v for k, v in os.environ.items()
              if k in ("NEBIUS_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                       "GOOGLE_API_KEY") and len(v) >= 12]


def git(*args) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout


def candidates() -> list[str]:
    out = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({p for p in out.decode().split("\0") if p and (REPO / p).is_file()})


def png_text_chunks(data: bytes) -> list[str]:
    found, i = [], 8
    while i + 8 <= len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        kind = data[i + 4:i + 8]
        if kind in (b"tEXt", b"iTXt", b"zTXt", b"eXIf"):
            found.append(kind.decode())
        i += 12 + length
    return found


def scan_text(name: str, text: str, problems: list):
    for label, rx in SECRETS.items():
        for m in rx.finditer(text):
            value = m.group(1) if rx.groups else m.group(0)
            if label == "key_assignment" and (PLACEHOLDER_OK.search(value) or value.isupper()
                                              or value.startswith(("os.environ", "self.", "settings."))):
                continue
            problems.append((name, "secret:" + label, value[:6] + "…"))
    for label, rx in PRIVATE.items():
        for m in rx.finditer(text):
            problems.append((name, "private:" + label, m.group(0)[:40]))
    for value in KEY_VALUES:
        if value in text:
            problems.append((name, "secret:live_key_value", "(value withheld)"))
    if TERMS:
        for m in TERMS.finditer(text):
            problems.append((name, "private:listed_term", m.group(0)[:2] + "…"))
    if HANGUL.search(text) and not HANGUL_OK.search(name):
        problems.append((name, "hangul", HANGUL.search(text).group(0)))


def audit_worktree(problems: list) -> int:
    files = candidates()
    for name in files:
        path = REPO / name
        if FORBIDDEN_NAME.search(name) and Path(name).name not in ALLOWED_FORBIDDEN:
            problems.append((name, "forbidden_file", ""))
        data = path.read_bytes()
        if len(data) > MAX_BYTES:
            problems.append((name, "oversize", f"{len(data)} bytes"))
        if data.startswith(b"\x89PNG"):
            chunks = png_text_chunks(data)
            if chunks:
                problems.append((name, "png_metadata", ",".join(chunks)))
            continue
        if b"\0" in data[:4096]:
            continue
        scan_text(name, data.decode("utf-8", "replace"), problems)
    return len(files)


def audit_history(problems: list) -> int:
    refs = git("for-each-ref", "--format=%(refname)").split()
    if not refs:
        return 0
    seen = 0
    objects = git("rev-list", "--objects", "--all").decode().splitlines()
    for line in objects:
        sha, _, name = line.partition(" ")
        if not name:
            continue
        if git("cat-file", "-t", sha).strip() != b"blob":
            continue
        seen += 1
        if FORBIDDEN_NAME.search(name) and Path(name).name not in ALLOWED_FORBIDDEN:
            problems.append(("history:" + name, "forbidden_file", sha[:10]))
        data = git("cat-file", "blob", sha)
        if data.startswith(b"\x89PNG") or b"\0" in data[:4096]:
            continue
        scan_text("history:" + name, data.decode("utf-8", "replace"), problems)
    return seen


def main():
    problems: list = []
    report = {"files": audit_worktree(problems)}
    if "--history" in sys.argv:
        report["history_blobs"] = audit_history(problems)
        report["commits"] = int(git("rev-list", "--all", "--count").strip() or 0) if report["history_blobs"] else 0
    report["problems"] = [{"file": f, "kind": k, "sample": s} for f, k, s in problems]
    report["result"] = "PASS" if not problems else "FAIL"
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for p in report["problems"]:
            print(f"{p['kind']:28} {p['file']}  {p['sample']}")
        extra = f", {report['history_blobs']} history blobs" if "history_blobs" in report else ""
        print(f"public audit: {report['result']} ({report['files']} files{extra}, {len(problems)} problems)")
    sys.exit(0 if not problems else 1)


if __name__ == "__main__":
    main()
