#!/usr/bin/env python3
"""Refresh data/fixtures/wikipedia-snapshots.json from the live English Wikipedia API.

Uses the same allowlisted, SSRF-resistant fetcher as the server. The snapshots
are short lead-section excerpts (CC BY-SA 4.0) with title, revision id and
retrieval date so attribution stays accurate. They power offline demos and
tests; the running app prefers live sources.
"""
import datetime
import json
import re
import sys
import time
from pathlib import Path
from urllib import parse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from otaku_gallery.errors import ResearchError  # noqa: E402
from otaku_gallery.fetch import safe_fetch  # noqa: E402

TITLES = ["Cyberpunk", "Ghost in the Shell", "Slice of life", "Hanami", "Yōkai", "Kitsune", "Magical girl",
          "Cardcaptor Sakura", "Mecha anime and manga", "Mobile Suit Gundam", "Iyashikei", "Yotsuba&!", "Isekai",
          "Castle in the Sky", "Visual novel", "Steins;Gate"]
MAX_CHARS = 1500


def trim(text):
    text = re.sub(r"\n{2,}", "\n", text.strip())
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind(".\n"))
    return cut[:end + 1] if end > 400 else cut


def main():
    out = []
    for query in TITLES:
        params = {"action": "query", "format": "json", "formatversion": "2", "redirects": "1", "titles": query,
                  "prop": "extracts|revisions", "exintro": "1", "explaintext": "1", "rvprop": "ids|timestamp"}
        for attempt in range(5):  # Wikipedia may answer 429 to bursts; back off politely
            try:
                data = safe_fetch("https://en.wikipedia.org/w/api.php?" + parse.urlencode(params))
                break
            except ResearchError as exc:
                if exc.code != "http_429" or attempt == 4:
                    raise
                time.sleep(8 * (attempt + 1))
        page = (data["query"]["pages"] or [{}])[0]
        if page.get("missing") or not page.get("extract"):
            print("skip (missing):", query, file=sys.stderr)
            continue
        rev = (page.get("revisions") or [{}])[0]
        aliases = sorted({query} - {page["title"]})
        out.append({"title": page["title"], "aliases": aliases, "text": trim(page["extract"]),
                    "revid": rev.get("revid"), "timestamp": rev.get("timestamp"),
                    "retrieved": datetime.date.today().isoformat()})
        print("ok:", page["title"], len(out[-1]["text"]), file=sys.stderr)
        time.sleep(2)
    doc = {"schema": 1,
           "note": "Lead-section excerpts from English Wikipedia, used as an offline fallback. Text is available under "
                   "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/); authors are the Wikipedia "
                   "contributors listed in each article's history. Excerpts were shortened.",
           "license": "CC-BY-SA-4.0", "records": out}
    path = ROOT / "data" / "fixtures" / "wikipedia-snapshots.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", path.relative_to(ROOT), len(out), "records", file=sys.stderr)


if __name__ == "__main__":
    main()
