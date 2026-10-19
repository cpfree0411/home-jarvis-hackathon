#!/usr/bin/env python3
"""Public-release audit. Exits non-zero if the tree contains anything that should not be published.

Checks every file that is not git-ignored (or every file, if the directory is not a git repo):
  - private/LAN IP addresses, user home paths, hostnames of private machines
  - credential-shaped strings, private-key blocks, bearer tokens, committed env files
  - the live NEBIUS_API_KEY value from the environment (never printed), in the tree and in git history
  - Hangul text (the English edition must stay English) and other-project/private-content markers
  - non-open licences in the artwork manifest, missing LICENSE/NOTICE, git remotes, SVG scripts/external refs

Usage:  python3 scripts/audit_repo.py [--root DIR] [--history]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SELF = Path(__file__).resolve()
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".css", ".html", ".md", ".json", ".txt", ".svg", ".sh", ".example", ".toml",
                 ".cfg", ".yml", ".yaml", ".service", ".gitignore", ""}
# Patterns are assembled from pieces so that this file does not match itself.
H = "/ho" + "me/"
CHECKS = [
    ("lan-ip", re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
    ("home-path", re.compile(re.escape(H) + r"[a-z_][a-z0-9_-]*|/Us" + r"ers/[A-Za-z]|[A-Z]:\\Us" + r"ers\\")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("token-shape", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})\b")),
    ("bearer-literal", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{24,}")),
    ("jwt-shape", re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}")),
    ("key-assignment", re.compile(r"(?i)\b(?:NEBIUS|OPENAI|ANTHROPIC|GEMINI|NVIDIA|HF|API)_?(?:API_?)?(?:KEY|TOKEN|SECRET)\s*[:=]\s*[\"']?(?!\s|[\"']|your|<|\$|changeme|example|none|null|xxx|os\.environ|self\.|environ|value|\()[A-Za-z0-9._-]{16,}")),
    ("hangul", re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")),
    ("private-markers", re.compile(r"(?i)\b(?:jar" + r"vis|pix" + r"iv|deviant" + r"art|dan" + r"booru|gel" + r"booru|kona" + r"chan|art" + r"station|antigrav" + r"ity|red22" + r"72|home[- ]?server|\bpi" + r"-?hole)\b")),
]
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "media", ".pytest_cache"}
FORBIDDEN_FILES = re.compile(r"(?i)(^|/)(\.env(\.(?!example$).*)?|.*\.(pem|key|p12|pfx|sqlite3?|db|log)|id_(rsa|ed25519)|.*credentials.*\.json|.*token.*\.json|\.netrc|\.pypirc)$")
ALLOWED_BINARY = {".png", ".jpg", ".jpeg", ".webp", ".ico", ".webm", ".mp4"}


def tracked_files(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, check=True)
        names = [n for n in out.stdout.splitlines() if n]
        if names or (root / ".git").exists():
            return [root / n for n in names]
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        found.extend(Path(dirpath) / f for f in files)
    return found


def audit(root, history=False):
    root = Path(root).resolve()
    findings = []

    def add(kind, where, detail=""):
        findings.append({"check": kind, "where": where, "detail": detail})

    files = [p for p in tracked_files(root) if p.is_file()]
    env_secret = (os.environ.get("NEBIUS_API_KEY") or "").strip()
    for path in files:
        rel = str(path.relative_to(root))
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            add("excluded-directory-in-public-tree", rel)
            continue
        if FORBIDDEN_FILES.search(rel):
            add("forbidden-file", rel)
            continue
        if path.stat().st_size > 1_500_000:
            add("large-file", rel, "%d bytes" % path.stat().st_size)
        suffix = path.suffix.lower()
        if suffix in ALLOWED_BINARY:
            if not rel.startswith("docs/screenshots/"):
                add("unreviewed-binary", rel)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            add("unexpected-binary", rel)
            continue
        for name, pattern in CHECKS:
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                add(name, "%s:%d" % (rel, line), "matched text withheld" if name in ("key-assignment", "token-shape", "bearer-literal", "jwt-shape") else m.group(0)[:60])
                break
        if len(env_secret) >= 8 and env_secret in text:
            add("live-secret-in-tree", rel, "value withheld")
        if suffix == ".svg":
            if re.search(r"<script|onload\s*=|javascript:|<foreignObject|<image\b[^>]*href\s*=\s*[\"']https?:|xlink:href\s*=\s*[\"']https?:", text, re.I):
                add("svg-active-or-external-content", rel)
    # licences and metadata
    lic = root / "LICENSE"
    if not lic.is_file() or not lic.read_text(encoding="utf-8").lstrip().startswith("MIT License"):
        add("license", "LICENSE", "missing or not the MIT License text")
    if not (root / "NOTICE").is_file():
        add("license", "NOTICE", "missing")
    manifest = root / "data" / "gallery.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for item in data.get("items", []):
            if item.get("license") not in {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "MIT", "PD"}:
                add("artwork-license", "data/gallery.json", "%s: %r" % (item.get("id"), item.get("license")))
            for key in ("creator", "license_label", "source_label"):
                if not item.get(key):
                    add("artwork-metadata", "data/gallery.json", "%s: missing %s" % (item.get("id"), key))
    # git remotes and history
    if (root / ".git").exists():
        remotes = subprocess.run(["git", "-C", str(root), "remote"], capture_output=True, text=True).stdout.split()
        if remotes:
            add("git-remote", ".git/config", "remotes configured: " + ",".join(remotes))
        if history and len(env_secret) >= 8:
            hit = subprocess.run(["git", "-C", str(root), "log", "--all", "-p", "--pickaxe-regex", "-S", re.escape(env_secret), "--format=%h"],
                                 capture_output=True, text=True)
            if hit.stdout.strip():
                add("live-secret-in-history", ".git", "value withheld")
        if history:
            for pattern in (r"\b(?:192\.168|10\.\d{1,3})\.\d{1,3}\.\d{1,3}\b", H + "[a-z]"):
                hit = subprocess.run(["git", "-C", str(root), "log", "--all", "-G", pattern, "--format=%h"], capture_output=True, text=True)
                if hit.stdout.strip():
                    add("history-private-path-or-ip", ".git", "commits: " + " ".join(hit.stdout.split()[:5]))
        author = subprocess.run(["git", "-C", str(root), "log", "--all", "--format=%ae"], capture_output=True, text=True).stdout.split()
        bad = sorted({a for a in author if not a.endswith("@users.noreply.github.com") and not a.endswith("@example.invalid")})
        if bad:
            add("commit-author-email", ".git", "non-anonymised author email(s): %d" % len(bad))
    return findings, len(files)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(SELF.parent.parent))
    ap.add_argument("--history", action="store_true", help="also inspect git history")
    args = ap.parse_args(argv)
    findings, count = audit(args.root, args.history)
    for f in findings:
        print("FINDING [%s] %s %s" % (f["check"], f["where"], f["detail"]))
    print("audited %d files: %s" % (count, "%d finding(s)" % len(findings) if findings else "clean"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
