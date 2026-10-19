"""Gallery manifest loading and validation.

Bundled artwork lives in web/art and is listed in data/gallery.json. Optional
extra, separately licensed media lives in media/
and is listed in media/gallery.json (git-ignored). Every entry must carry honest
creator and licence metadata or it is rejected at startup.
"""
import json
import re
from pathlib import Path

from .textutil import clean, normalize_query

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.(?:svg|png|jpg|jpeg|webp)$")
# Licences that permit redistribution with the attribution shown in the UI.
OPEN_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "CC-BY-SA-4.0", "CC-BY-SA-3.0", "CC-BY-2.0",
                 "CC-BY-SA-2.0", "PD", "MIT"}


class ManifestError(ValueError):
    pass


def _text(entry, key, limit, required=True):
    value = clean(entry.get(key), limit)
    if required and not value:
        raise ManifestError("%s: missing %s" % (entry.get("id", "?"), key))
    return value


def _https_or_empty(value):
    return value if isinstance(value, str) and re.match(r"^https://[^\s<>\"']{1,300}$", value) else ""


def validate_item(entry, origin):
    if not isinstance(entry, dict) or not ID_RE.match(str(entry.get("id", ""))):
        raise ManifestError("invalid artwork id")
    item_id = entry["id"]
    filename = str(entry.get("file", ""))
    if not FILE_RE.match(filename):
        raise ManifestError("%s: invalid file name" % item_id)
    license_id = str(entry.get("license", ""))
    if license_id not in OPEN_LICENSES:
        raise ManifestError("%s: licence %r is not on the redistribution allow-list" % (item_id, license_id))
    topics = []
    for raw in (entry.get("topics") or [])[:6]:
        label, query = clean(raw.get("label"), 60), normalize_query(raw.get("query", ""))
        tid = str(raw.get("id", ""))
        if not (label and query and ID_RE.match(tid)):
            raise ManifestError("%s: invalid topic" % item_id)
        topics.append({"id": tid, "label": label, "query": query, "relation": clean(raw.get("relation"), 40)})
    tags = [clean(t, 24).lower() for t in (entry.get("tags") or [])[:8] if clean(t, 24)]
    return {
        "id": item_id, "origin": origin, "file": filename,
        "url": ("art/" if origin == "bundled" else "media/") + filename,
        "title": _text(entry, "title", 80), "description": _text(entry, "description", 400),
        "alt": _text(entry, "alt", 240), "tags": tags,
        "creator": _text(entry, "creator", 120), "creator_kind": _text(entry, "creator_kind", 40),
        "license": license_id, "license_label": _text(entry, "license_label", 60),
        "license_url": _https_or_empty(entry.get("license_url")),
        "source_label": _text(entry, "source_label", 120), "source_note": clean(entry.get("source_note"), 240), "source_url": _https_or_empty(entry.get("source_url")),
        "accent": entry.get("accent") if re.match(r"^#[0-9a-fA-F]{6}$", str(entry.get("accent", ""))) else "#e6d3a4",
        "topics": topics,
    }


class Gallery:
    def __init__(self, bundled_manifest, art_dir, local_manifest=None, media_dir=None):
        self.items, self.files = [], {}
        self._load(bundled_manifest, "bundled", Path(art_dir))
        if local_manifest and Path(local_manifest).is_file():
            self._load(local_manifest, "local", Path(media_dir or Path(local_manifest).parent))
        if not self.items:
            raise ManifestError("the gallery is empty")

    def _load(self, manifest, origin, directory):
        data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        for entry in data.get("items", []):
            item = validate_item(entry, origin)
            if item["id"] in {i["id"] for i in self.items}:
                raise ManifestError("duplicate artwork id " + item["id"])
            path = (directory / item["file"]).resolve()
            if not path.is_file() or directory.resolve() not in path.parents:
                raise ManifestError("%s: file not found in %s" % (item["id"], origin))
            self.items.append(item)
            self.files[(origin, item["file"])] = path

    def get(self, item_id):
        return next((i for i in self.items if i["id"] == item_id), None)

    def path_for(self, origin, filename):
        return self.files.get((origin, filename))

    def public(self):
        return [{k: v for k, v in item.items() if k not in ("file", "origin")} for item in self.items]
