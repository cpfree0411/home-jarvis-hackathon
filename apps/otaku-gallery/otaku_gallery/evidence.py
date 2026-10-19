"""Evidence gathering: public Wikipedia and AniList records fetched by the server.

Records are plain dicts: id, provider, host, kind, title, url, text, license,
disambiguation, fixture. The model sees only id/provider/kind/title/text; the
URLs shown to people always come from these records, never from model output.
"""
import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib import parse

from .errors import ResearchError
from .fetch import safe_fetch
from .textutil import ADULT_GENRES, clean, is_adult_text, query_key

logger = logging.getLogger("otaku-gallery.evidence")

EVIDENCE_BUDGET_S = 9.0
WIKI_LICENSE = "CC BY-SA 4.0 (text from Wikipedia contributors)"
ANILIST_LICENSE = "AniList data, shown as a short excerpt with attribution"
MAX_RECORDS = 6
TEXT_BUDGET = 12000

ANILIST_QUERY = """query($s:String!){
 works:Page(page:1,perPage:3){media(search:$s,isAdult:false,sort:SEARCH_MATCH){
  id type format status title{romaji english native} startDate{year} genres isAdult
  episodes chapters description(asHtml:false) studios(isMain:true){nodes{name}}}}
 people:Page(page:1,perPage:2){characters(search:$s,sort:SEARCH_MATCH){
  id name{full native} description(asHtml:false)
  media(perPage:4,sort:POPULARITY_DESC){nodes{id type isAdult genres title{romaji english native}}}}}
}"""


def wiki_url(title):
    return "https://en.wikipedia.org/wiki/" + parse.quote(title.replace(" ", "_"), safe="()_,.!~*'-:")


def wiki_search(query, fetch=safe_fetch):
    params = {
        "action": "query", "format": "json", "formatversion": "2", "redirects": "1",
        "generator": "search", "gsrsearch": query, "gsrlimit": "4", "gsrnamespace": "0",
        "prop": "extracts|pageprops|categories", "exintro": "1", "explaintext": "1", "exlimit": "4",
        "exchars": "2400", "ppprop": "disambiguation", "cllimit": "max", "clshow": "!hidden",
    }
    data = fetch("https://en.wikipedia.org/w/api.php?" + parse.urlencode(params))
    pages = sorted((data.get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 99))
    records, dropped = [], 0
    for page in pages[:4]:
        title = clean(page.get("title"), 160)
        if not title or page.get("missing"):
            continue
        categories = " ".join(clean(c.get("title"), 120) for c in page.get("categories") or [])
        extract = clean(page.get("extract"), 2400)
        if is_adult_text(title, categories, extract[:600]):
            dropped += 1
            continue
        records.append({
            "provider": "Wikipedia (English)", "host": "en.wikipedia.org", "kind": "encyclopedia",
            "title": title, "url": wiki_url(title), "text": extract, "license": WIKI_LICENSE,
            "disambiguation": "disambiguation" in (page.get("pageprops") or {}), "fixture": False,
        })
    return records, dropped


def _titles(title):
    return [t for t in (clean(title.get(k), 160) for k in ("native", "romaji", "english")) if t]


def _strip_spoilers(text):
    """AniList wraps spoilers as ~!...!~; they never reach the model."""
    text = re.sub(r"~!.*?!~", " ", text or "", flags=re.S)
    return re.sub(r"<[^>]{0,80}>", " ", text)


def anilist_search(query, fetch=safe_fetch):
    data = fetch("https://graphql.anilist.co", body=json.dumps({"query": ANILIST_QUERY, "variables": {"s": query}}).encode())
    if data.get("errors"):
        raise ResearchError("provider_error")
    data = data.get("data") or {}
    records, dropped = [], 0
    kinds = {"ANIME": "anime", "MANGA": "manga"}
    for media in ((data.get("works") or {}).get("media") or [])[:3]:
        identity, kind = media.get("id"), media.get("type")
        genres = [clean(g, 40) for g in media.get("genres") or []]
        titles = _titles(media.get("title") or {})
        description = clean(_strip_spoilers(media.get("description")), 1000)
        if (media.get("isAdult") is not False or kind not in kinds or not isinstance(identity, int) or not titles
                or {g.casefold() for g in genres} & ADULT_GENRES or is_adult_text(description, *titles)):
            dropped += 1
            continue
        studios = [clean(n.get("name"), 80) for n in (media.get("studios") or {}).get("nodes") or []]
        year = (media.get("startDate") or {}).get("year")
        lines = ["Type: %s / %s" % (kind, clean(media.get("format"), 20)), "Titles: " + " / ".join(titles)]
        if isinstance(year, int):
            lines.append("Start year: %d" % year)
        if genres:
            lines.append("Genres: " + ", ".join(genres))
        if any(studios):
            lines.append("Main studio: " + ", ".join(s for s in studios if s))
        for key, label in (("episodes", "Episodes"), ("chapters", "Chapters")):
            if isinstance(media.get(key), int):
                lines.append("%s: %d" % (label, media[key]))
        if description:
            lines.append("Description: " + description)
        records.append({
            "provider": "AniList", "host": "anilist.co", "kind": kinds[kind], "title": titles[-1],
            "url": "https://anilist.co/%s/%d" % (kind.lower(), identity), "text": "\n".join(lines),
            "license": ANILIST_LICENSE, "disambiguation": False, "fixture": False,
        })
    for person in ((data.get("people") or {}).get("characters") or [])[:2]:
        identity = person.get("id")
        name = clean((person.get("name") or {}).get("full"), 120)
        works = (person.get("media") or {}).get("nodes") or []
        safe_works = [w for w in works if w.get("isAdult") is False
                      and not {str(g).casefold() for g in w.get("genres") or []} & ADULT_GENRES]
        description = clean(_strip_spoilers(person.get("description")), 1000)
        if not isinstance(identity, int) or not name or not safe_works \
                or is_adult_text(description, name):
            dropped += 1
            continue
        appears = [" / ".join(_titles(w.get("title") or {})[-2:]) for w in safe_works]
        native = clean((person.get("name") or {}).get("native"), 80)
        lines = ["Type: CHARACTER", "Name: " + name + (" / " + native if native else ""),
                 "Selected all-ages appearances: " + "; ".join(a for a in appears if a)]
        if description:
            lines.append("Description: " + description)
        records.append({
            "provider": "AniList", "host": "anilist.co", "kind": "character", "title": name,
            "url": "https://anilist.co/character/%d" % identity, "text": "\n".join(lines),
            "license": ANILIST_LICENSE, "disambiguation": False, "fixture": False,
        })
    return records, dropped


# ---------------------------------------------------------------- bundled snapshots

class Fixtures:
    """Bundled, attributed Wikipedia snapshots used when the live sites are unreachable."""

    def __init__(self, path):
        self.records = []
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for entry in data.get("records", []):
            if not isinstance(entry, dict) or not entry.get("title") or not entry.get("text"):
                continue
            keys = {query_key(entry["title"])} | {query_key(a) for a in entry.get("aliases", [])}
            self.records.append((keys, entry))

    def search(self, query):
        wanted = query_key(query)
        if not wanted:
            return []
        exact = [e for keys, e in self.records if wanted in keys]
        loose = [e for keys, e in self.records if e not in exact and len(wanted) >= 5
                 and any(wanted in k or k in wanted for k in keys if len(k) >= 5)]
        out = []
        for entry in (exact + loose)[:3]:
            out.append({
                "provider": "Wikipedia (English) · bundled snapshot", "host": "en.wikipedia.org",
                "kind": "encyclopedia", "title": clean(entry["title"], 160), "url": wiki_url(entry["title"]),
                "text": clean(entry["text"], 2400), "license": WIKI_LICENSE, "disambiguation": False,
                "fixture": True, "snapshot_date": clean(entry.get("retrieved", ""), 20),
                "revision": entry.get("revid"),
            })
        return out


def gather_evidence(query, mode="auto", fixtures=None, fetch=safe_fetch, deadline=None, cancelled=None):
    """Bounded, parallel, read-only lookups. mode: live | fixture | auto. Returns (records, notes)."""
    deadline = deadline or time.monotonic() + EVIDENCE_BUDGET_S
    results, notes, lock = {}, {"failed": [], "filtered_adult": 0, "mode": mode}, threading.Lock()

    def run(name, fn):
        try:
            records, dropped = fn(query, fetch=fetch)
            with lock:
                results[name] = records
                notes["filtered_adult"] += dropped
        except ResearchError as exc:
            with lock:
                notes["failed"].append({"source": name, "reason": exc.code})
        except Exception:  # noqa: BLE001 - one provider never sinks the others
            logger.exception("evidence_error source=%s", name)
            with lock:
                notes["failed"].append({"source": name, "reason": "invalid_metadata"})

    wiki, anilist = [], []
    if mode in ("live", "auto"):
        threads = [threading.Thread(target=run, args=(n, f), daemon=True)
                   for n, f in (("wikipedia", wiki_search), ("anilist", anilist_search))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(max(0.0, deadline - time.monotonic()))
        with lock:
            wiki, anilist = list(results.get("wikipedia", [])), list(results.get("anilist", []))
            for name in ("wikipedia", "anilist"):
                if name not in results and not any(f["source"] == name for f in notes["failed"]):
                    notes["failed"].append({"source": name, "reason": "timeout"})
    used = "live"
    if (mode == "fixture" or (mode == "auto" and not wiki)) and fixtures is not None and not (cancelled and cancelled()):
        snap = fixtures.search(query)
        if snap:
            wiki, used = snap, ("fixture" if not anilist else "live+fixture")
    notes["used"] = used if (wiki or anilist) else "none"
    records = []
    for group in zip(*[(g + [None] * 3)[:3] for g in (wiki, anilist)]):
        records.extend(r for r in group if r)
    records.extend(r for r in wiki[3:] if r not in records)
    records = records[:MAX_RECORDS]
    budget = TEXT_BUDGET
    for index, record in enumerate(records, 1):
        record["id"] = "S%d" % index
        record["text"] = record["text"][:max(300, min(len(record["text"]), budget))]
        budget = max(0, budget - len(record["text"]))
    return records, notes


def evidence_for_model(records):
    return json.dumps(
        [{k: r[k] for k in ("id", "provider", "kind", "title", "text")}
         | ({"is_disambiguation_page": True} if r.get("disambiguation") else {}) for r in records],
        ensure_ascii=False, indent=1)
