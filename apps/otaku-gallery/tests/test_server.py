import http.client
import json
import threading
import time
import unittest
from functools import partial
from pathlib import Path

from otaku_gallery.app import build_app
from otaku_gallery.config import Config
from otaku_gallery.evidence import Fixtures, gather_evidence
from otaku_gallery.server import make_server, serve_in_thread
from tests.helpers import StubWriter

ROOT = Path(__file__).resolve().parent.parent


class ServerTests(unittest.TestCase):
    def setUp(self):
        base = Config.from_env()
        self.config = Config(**{**base.__dict__, "evidence_mode": "fixture", "cache_ttl": 0, "rate_max_runs": 100,
                               "local_manifest": ROOT / "media" / "none.json"})
        fx = Fixtures(ROOT / "data" / "fixtures" / "wikipedia-snapshots.json")
        self.writer = StubWriter()
        self.app = build_app(self.config, writer=self.writer, gather=partial(gather_evidence, mode="fixture", fixtures=fx))
        self.server = make_server(self.app, "127.0.0.1", 0)
        serve_in_thread(self.server)
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        return resp, payload

    def jcall(self, *a, **k):
        resp, payload = self.call(*a, **k)
        return resp, json.loads(payload)

    def wait_done(self, sid):
        for _ in range(100):
            _, view = self.jcall("GET", "/api/research/" + sid)
            if view["status"] not in ("queued", "running"):
                return view
            time.sleep(0.05)
        self.fail("research did not finish")

    # ---- static + health
    def test_health_has_no_secrets(self):
        resp, data = self.jcall("GET", "/health")
        self.assertEqual(resp.status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["model"], "nvidia/Nemotron-3-Ultra-550b-a55b")
        self.assertEqual(data["artworks"], 8)
        self.assertIs(data["nebius_configured"], True)
        self.assertNotIn("key", json.dumps(data).replace("nebius_configured", ""))

    def test_index_and_assets_use_relative_urls(self):
        resp, body = self.call("GET", "/")
        html = body.decode()
        self.assertEqual(resp.status, 200)
        self.assertIn('lang="en"', html)
        for ref in ("app.css", "app.js", "research.js", "strings.js", "research.css", "favicon.svg"):
            self.assertIn('"%s"' % ref, html)
            self.assertEqual(self.call("GET", "/" + ref)[0].status, 200, ref)
        self.assertNotIn('src="/', html)
        self.assertNotIn('href="/', html)
        js = self.call("GET", "/app.js")[1].decode() + self.call("GET", "/research.js")[1].decode()
        self.assertNotIn("fetch('/", js)
        self.assertNotIn('fetch("/', js)

    def test_security_headers(self):
        resp, _ = self.call("GET", "/")
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        csp = resp.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("frame-ancestors 'self'", csp)
        self.assertEqual(resp.getheader("Referrer-Policy"), "no-referrer")
        svg = self.call("GET", "/art/neon-rooftop-rain.svg")[0]
        self.assertEqual(svg.getheader("Content-Type"), "image/svg+xml")
        self.assertIn("sandbox", svg.getheader("Content-Security-Policy"))

    def test_gallery_listing_has_license_metadata_and_hides_paths(self):
        _, data = self.jcall("GET", "/api/gallery")
        self.assertEqual(len(data["items"]), 8)
        for item in data["items"]:
            self.assertEqual(item["license"], "CC0-1.0")
            self.assertTrue(item["creator"] and item["alt"] and item["topics"])
            self.assertNotIn("file", item)
            self.assertEqual(self.call("GET", "/" + item["url"])[0].status, 200)
        self.assertNotIn("/home", json.dumps(data))

    def test_path_traversal_and_unknown_files(self):
        for path in ("/art/../server.py", "/art/%2e%2e/config.py", "/../etc/passwd", "/art/secret.svg", "/media/x.png",
                     "/data/gallery.json", "/otaku_gallery/server.py", "/.env", "/.git/config", "/app.js/../../x",
                     "/web/index.html", "/%2e%2e%2fREADME.md", "/art/neon-rooftop-rain.svg/../../README.md"):
            resp, payload = self.call("GET", path)
            self.assertEqual(resp.status, 404, path)
            self.assertNotIn(b"def ", payload, path)

    # ---- research API
    def test_post_requires_json_content_type_and_same_origin(self):
        resp, data = self.jcall("POST", "/api/research", raw=b'{"query":"x"}', headers={"Content-Type": "text/plain"})
        self.assertEqual((resp.status, data["error"]["code"]), (415, "unsupported_media_type"))
        resp, data = self.jcall("POST", "/api/research", body={"query": "Cyberpunk"}, headers={"Origin": "https://evil.example"})
        self.assertEqual((resp.status, data["error"]["code"]), (403, "forbidden_origin"))
        ok, _ = self.jcall("POST", "/api/research", body={"query": "Cyberpunk"}, headers={"Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(ok.status, 200)

    def test_bad_requests_get_english_errors(self):
        cases = [(dict(raw=b"{not json", headers={"Content-Type": "application/json"}), 400, "bad_json"),
                 (dict(body=["x"]), 400, "bad_request"), (dict(body={}), 400, "bad_request"),
                 (dict(body={"query": 5}), 400, "bad_request"),
                 (dict(body={"item_id": "nope", "topic_id": "x"}), 404, "unknown_artwork"),
                 (dict(body={"item_id": "neon-rooftop-rain", "topic_id": "nope"}), 404, "unknown_topic"),
                 (dict(raw=b"x" * 5000, headers={"Content-Type": "application/json"}), 413, "payload_too_large")]
        for kwargs, status, code in cases:
            resp, data = self.jcall("POST", "/api/research", **kwargs)
            self.assertEqual((resp.status, data["error"]["code"]), (status, code), kwargs.keys())
            self.assertTrue(data["error"]["message"].isascii() and data["error"]["message"].endswith((".", "?")))

    def test_topic_research_end_to_end(self):
        resp, view = self.jcall("POST", "/api/research", body={"item_id": "neon-rooftop-rain", "topic_id": "cyberpunk"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(view["query"], "Cyberpunk")  # resolved server-side from the manifest
        done = self.wait_done(view["id"])
        self.assertEqual(done["status"], "done")
        page = done["page"]
        self.assertEqual(page["status"], "answered")
        self.assertEqual(page["sources"][0]["url"], "https://en.wikipedia.org/wiki/Cyberpunk")
        self.assertTrue(page["sources"][0]["bundled_snapshot"])
        self.assertEqual(done["context"]["topic"], "Cyberpunk")

    def test_client_cannot_inject_a_query_through_topic_ids(self):
        resp, data = self.jcall("POST", "/api/research", body={"item_id": "neon-rooftop-rain", "topic_id": "cyberpunk", "query": "hentai"})
        self.assertEqual(data["query"], "Cyberpunk")

    def test_poll_unknown_and_cancel(self):
        self.assertEqual(self.jcall("GET", "/api/research/doesnotexist1")[0].status, 404)
        resp, data = self.jcall("POST", "/api/research/doesnotexist1/cancel", body={})
        self.assertEqual(resp.status, 404)
        resp, data = self.jcall("GET", "/api/research/!!bad")
        self.assertEqual(resp.status, 404)

    def test_methods(self):
        self.assertEqual(self.jcall("PUT", "/api/research", body={})[0].status, 405)
        self.assertEqual(self.call("HEAD", "/health")[0].status, 200)
        self.assertEqual(self.call("GET", "/nope")[0].status, 404)

    def test_no_cors_headers(self):
        resp, _ = self.call("GET", "/api/gallery", headers={"Origin": "https://evil.example"})
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))

    def test_null_and_spoofed_forwarded_origins_are_rejected(self):
        for origin in ("null", "file://", "https://evil.example"):
            resp, data = self.jcall("POST", "/api/research", body={"query": "Cyberpunk"},
                                   headers={"Origin": origin, "X-Forwarded-Host": "evil.example"})
            self.assertEqual((resp.status, data["error"]["code"]), (403, "forbidden_origin"))


if __name__ == "__main__":
    unittest.main()
