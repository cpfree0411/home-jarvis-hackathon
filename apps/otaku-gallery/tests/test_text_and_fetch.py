import unittest

from otaku_gallery.errors import ResearchError
from otaku_gallery.fetch import resolve_public, safe_fetch, validate_url
from otaku_gallery.textutil import is_adult_text, normalize_query, query_key


class TextTests(unittest.TestCase):
    def test_normalize_query_strips_markup_and_limits_length(self):
        self.assertEqual(normalize_query("  <b>Cyberpunk</b> \n {x} "), "b Cyberpunk /b x")
        self.assertEqual(len(normalize_query("a" * 500)), 80)
        self.assertEqual(normalize_query("!!! ???"), "")
        self.assertEqual(normalize_query(None), "")

    def test_query_key_is_case_and_punctuation_insensitive(self):
        self.assertEqual(query_key("Steins;Gate"), query_key("steins gate"))

    def test_adult_filter(self):
        self.assertTrue(is_adult_text("some hentai title"))
        self.assertTrue(is_adult_text("NSFW"))
        self.assertFalse(is_adult_text("Cardcaptor Sakura"))
        self.assertFalse(is_adult_text("Essex County"))  # no substring false positives


class UrlSafetyTests(unittest.TestCase):
    def test_allowed(self):
        self.assertEqual(validate_url("https://en.wikipedia.org/w/api.php?a=1"), ("en.wikipedia.org", "/w/api.php?a=1"))
        self.assertEqual(validate_url("https://graphql.anilist.co")[0], "graphql.anilist.co")

    def test_rejected(self):
        bad = ["http://en.wikipedia.org/", "https://evil.example/", "https://en.wikipedia.org.evil.example/",
               "https://user:pw@en.wikipedia.org/", "https://en.wikipedia.org:8443/", "https://en.wikipedia.org/#x",
               "https://127.0.0.1/", "https://localhost/", "ftp://en.wikipedia.org/", "file:///etc/passwd",
               "https://en.wikipedia.org@evil.example/", "//en.wikipedia.org/", "", None, 5, "https://" + "a" * 3000]
        for url in bad:
            with self.assertRaises(ResearchError, msg=repr(url)[:50]):
                validate_url(url)

    def test_resolver_blocks_private_and_loopback(self):
        for addr in ("127.0.0.1", ".".join(['10', '1', '2', '3']), ".".join(['192', '168', '1', '5']), "169.254.169.254", "::1", "fd00::1", "::ffff:" + ".".join(["10", "0", "0", "1"])):
            resolver = lambda host, port, type=None, a=addr: [(0, 0, 0, "", (a, 443))]
            with self.assertRaises(ResearchError, msg=addr):
                resolve_public("en.wikipedia.org", resolver)

    def test_resolver_blocks_mixed_answers_and_literals(self):
        mixed = lambda host, port, type=None: [(0, 0, 0, "", ("8.8.8.8", 443)), (0, 0, 0, "", (".".join(['10', '0', '0', '1']), 443))]
        with self.assertRaises(ResearchError):
            resolve_public("en.wikipedia.org", mixed)
        with self.assertRaises(ResearchError):
            resolve_public("8.8.8.8")

    def test_resolver_pins_public_ipv4_first(self):
        ok = lambda host, port, type=None: [(0, 0, 0, "", ("2606:4700::1", 443)), (0, 0, 0, "", ("93.184.216.34", 443))]
        self.assertEqual(resolve_public("en.wikipedia.org", ok), "93.184.216.34")

    def test_safe_fetch_refuses_redirects_and_oversize(self):
        public = lambda host, port, type=None: [(0, 0, 0, "", ("93.184.216.34", 443))]

        class Conn:
            status, body = 302, b"{}"

            def __init__(self, host, address, timeout):
                self.address = address

            def request(self, *a, **k):
                pass

            def getresponse(self):
                outer = self

                class R:
                    status = Conn.status

                    def read(self, n):
                        return Conn.body[:n]
                return R()

            def close(self):
                pass
        with self.assertRaises(ResearchError) as cm:
            safe_fetch("https://en.wikipedia.org/w/api.php", resolver=public, connection=Conn)
        self.assertEqual(cm.exception.code, "http_302")
        Conn.status, Conn.body = 200, b"x" * 500_000
        with self.assertRaises(ResearchError) as cm:
            safe_fetch("https://en.wikipedia.org/w/api.php", resolver=public, connection=Conn)
        self.assertEqual(cm.exception.code, "oversize")
        Conn.body = b'{"ok": true}'
        self.assertEqual(safe_fetch("https://en.wikipedia.org/w/api.php", resolver=public, connection=Conn), {"ok": True})


if __name__ == "__main__":
    unittest.main()
