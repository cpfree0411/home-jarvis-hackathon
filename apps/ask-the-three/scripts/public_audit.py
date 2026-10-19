#!/usr/bin/env python3
"""Audit the Git candidate file set without printing matching secret values."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile("/" + "home" + "/[a-z]"),
    re.compile("/" + "Users" + "/[a-z]"),
    re.compile(r"192\.168\." + r"\d"),
    re.compile(r"10\.\d+\.\d+\." + r"\d"),
    re.compile(r"172\.(?:1[6-9]|2\d|3[01])\." + r"\d"),
    re.compile(r"(sk|nb|key)-[A-Za-z0-9_-]{24,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\."),
    re.compile("BEGIN [A-Z ]*PRIVATE" + " KEY"),
    re.compile("jarvis-" + "pi|ssh " + "jp"),
    re.compile("nev" + "ius"),
    re.compile("[%s-%s%s-%s%s-%s]" % tuple(map(chr, (0x1100, 0x11ff, 0x3130, 0x318f, 0xac00, 0xd7af)))),
]
TEXT = {".py", ".js", ".css", ".html", ".md", ".toml", ".txt", ".example", ".sh", ".json", ".service", ""}
BAD = {".db", ".sqlite", ".sqlite3", ".wav", ".flac", ".mp3", ".log", ".key", ".pem", ".whl"}


def main():
    names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                    cwd=ROOT).decode().split("\0")
    errors, count = [], 0
    for name in sorted(set(names) - {""}):
        p = ROOT / name
        count += 1
        if p.is_symlink() or p.suffix in BAD or p.name == ".env" or any(
                part in {".venv", "__pycache__", "state", "runtime"} for part in p.parts):
            errors.append({"path": name, "kind": "forbidden-file"})
            continue
        data = p.read_bytes()
        if p.suffix in TEXT:
            for i, pattern in enumerate(PATTERNS):
                if pattern.search(data.decode("utf-8")):
                    errors.append({"path": name, "kind": f"text-pattern-{i}"})
        elif p.suffix == ".png" and name.startswith("docs/screenshots/"):
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                errors.append({"path": name, "kind": "png-signature"})
            offset = 8
            while offset + 12 <= len(data):
                size = struct.unpack(">I", data[offset:offset + 4])[0]
                kind = data[offset + 4:offset + 8]
                if kind in (b"tEXt", b"iTXt", b"zTXt", b"eXIf"):
                    errors.append({"path": name, "kind": "image-metadata"})
                offset += size + 12
        elif p.suffix == ".woff2" and name.startswith("ask_three_en/web/fonts/"):
            if not data.startswith(b"wOF2"):
                errors.append({"path": name, "kind": "font-signature"})
        else:
            errors.append({"path": name, "kind": "unreviewed-file-type"})
    hashes = {}
    for font in ("Gaegu", "Nunito"):
        license_path = ROOT / f"ask_three_en/web/fonts/OFL-{font}.txt"
        text = license_path.read_text()
        if "SIL OPEN FONT LICENSE Version 1.1" not in text or f"The {font} Project Authors" not in text:
            errors.append({"path": str(license_path.relative_to(ROOT)), "kind": "font-license"})
        for p in (ROOT / "ask_three_en/web/fonts").glob(f"{font}*.woff2"):
            hashes[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    for name in ("README.md", "LICENSE", "NOTICE", "docs/INTEGRATION.md"):
        if not (ROOT / name).is_file():
            errors.append({"path": name, "kind": "missing-public-material"})
    print(json.dumps({"public_audit": "FAIL" if errors else "PASS", "candidate_files": count,
                      "font_sha256": hashes, "errors": errors}, indent=2))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
