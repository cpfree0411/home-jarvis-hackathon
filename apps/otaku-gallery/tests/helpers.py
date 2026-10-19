"""Shared test helpers: fake sources, a fake Nebius HTTPS connection and a stub writer."""
import json

from otaku_gallery.nebius import MODEL


def wiki_payload(titles=("Cyberpunk",), text="Cyberpunk is a subgenre of science fiction set in a dystopian future, 1984."):
    return {"query": {"pages": [{"index": i + 1, "title": t, "pageid": 100 + i, "extract": text,
                                 "categories": [{"title": "Category:Science fiction themes"}]}
                                for i, t in enumerate(titles)]}}


def anilist_payload():
    return {"data": {
        "works": {"media": [
            {"id": 30, "type": "ANIME", "format": "TV", "title": {"romaji": "Shinseiki Evangelion", "english": "Neon Genesis Evangelion", "native": None},
             "startDate": {"year": 1995}, "genres": ["Action", "Drama"], "isAdult": False, "episodes": 26, "chapters": None,
             "description": "A teenager pilots a giant machine. ~!Secret twist here!~ Many fans love it.",
             "studios": {"nodes": [{"name": "Gainax"}]}},
            {"id": 31, "type": "ANIME", "format": "OVA", "title": {"romaji": "Explicit Title", "english": None, "native": None},
             "startDate": {"year": 2001}, "genres": ["Hentai"], "isAdult": False, "description": "x", "studios": {"nodes": []}},
            {"id": 32, "type": "ANIME", "format": "TV", "title": {"romaji": "Unflagged", "english": None, "native": None},
             "startDate": {"year": 2002}, "genres": ["Comedy"], "isAdult": True, "description": "x", "studios": {"nodes": []}},
        ]},
        "people": {"characters": [
            {"id": 77, "name": {"full": "Rei Ayanami", "native": None}, "description": "A pilot.",
             "media": {"nodes": [{"id": 30, "type": "ANIME", "isAdult": False, "genres": ["Drama"],
                                  "title": {"romaji": "Shinseiki Evangelion", "english": "Neon Genesis Evangelion", "native": None}}]}},
        ]}}}


class FakeFetch:
    """Replaces safe_fetch: routes by URL and records calls."""

    def __init__(self, wiki=None, anilist=None, fail=()):
        self.wiki, self.anilist, self.fail, self.calls = wiki, anilist, set(fail), []

    def __call__(self, url, body=None, **kw):
        from otaku_gallery.errors import ResearchError
        self.calls.append(url)
        if "wikipedia.org" in url:
            if "wikipedia" in self.fail:
                raise ResearchError("http_429")
            return self.wiki if self.wiki is not None else {"query": {"pages": []}}
        if "anilist" in url:
            if "anilist" in self.fail:
                raise ResearchError("fetch_failed")
            return self.anilist if self.anilist is not None else {"data": {"works": {"media": []}, "people": {"characters": []}}}
        raise AssertionError(url)


def good_draft(sid="S1", **over):
    draft = {"status": "answered", "entity_kind": "genre", "title": "Cyberpunk", "title_original": "",
             "tagline": "Science fiction in a dystopian future.",
             "overview": "Cyberpunk is a subgenre of science fiction set in a dystopian future.",
             "overview_source_ids": [sid], "primary_source_id": sid,
             "sections": [{"heading": "Setting", "body": "Stories take place in a dystopian future.", "source_ids": [sid]}],
             "facts": [{"label": "Genre", "value": "Science fiction", "source_ids": [sid]}],
             "related": [], "candidates": [], "confidence": "high", "confidence_reason": "The source is on point.",
             "limits": "Only one source was read.", "age_appropriate": True}
    draft.update(over)
    return draft


def sample_records(text="Cyberpunk is a subgenre of science fiction set in a dystopian future, 1984. William Gibson wrote Neuromancer."):
    return [{"id": "S1", "provider": "Wikipedia (English)", "host": "en.wikipedia.org", "kind": "encyclopedia",
             "title": "Cyberpunk", "url": "https://en.wikipedia.org/wiki/Cyberpunk", "text": text,
             "license": "CC BY-SA 4.0", "disambiguation": False, "fixture": False}]


class StubWriter:
    model = MODEL

    def __init__(self, draft=None, error=None, delay=0.0, configured=True):
        self.draft, self.error, self.delay, self._configured = draft, error, delay, configured
        self.usage, self.calls, self.cancelled_calls = {}, [], 0

    def configured(self):
        return self._configured

    def cancel(self):
        self.cancelled_calls += 1

    def write(self, query, records, timeout=35, cancelled=None):
        import time
        from otaku_gallery.errors import ResearchError
        self.calls.append((query, [r["id"] for r in records]))
        end = time.monotonic() + self.delay
        while time.monotonic() < end:
            if cancelled and cancelled():
                raise ResearchError("cancelled")
            time.sleep(0.01)
        if self.error:
            raise ResearchError(self.error)
        self.usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        return self.draft if self.draft is not None else good_draft(), 5


class FakeResponse:
    def __init__(self, status, body):
        self.status, self._body = status, body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]


class FakeConnection:
    """Stand-in for http.client.HTTPSConnection; records the request instead of sending it."""
    last = None

    def __init__(self, host, timeout=None, response=None):
        self.host, self.timeout, self.sock = host, timeout, None
        self.request_args = None
        FakeConnection.last = self

    response = None  # set by factory()

    def request(self, method, target, body=None, headers=None):
        self.request_args = (method, target, body, headers)

    def getresponse(self):
        return type(self).response

    def close(self):
        pass


def conn_factory(status=200, body=None):
    cls = type("Conn", (FakeConnection,), {})
    cls.response = FakeResponse(status, body if body is not None else {})
    return cls


def nebius_body(draft=None, model=MODEL, finish="stop", tool_calls=None, content=None):
    message = {"role": "assistant", "content": content if content is not None else json.dumps(draft if draft is not None else good_draft())}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"model": model, "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168}}
