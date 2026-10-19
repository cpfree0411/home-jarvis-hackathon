import json
import tempfile
import time
import unittest
from pathlib import Path

from otaku_gallery.evidence import Fixtures, anilist_search, evidence_for_model, gather_evidence, wiki_search
from tests.helpers import FakeFetch, anilist_payload, wiki_payload

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "data" / "fixtures" / "wikipedia-snapshots.json"


class WikipediaTests(unittest.TestCase):
    def test_parses_and_labels_records(self):
        records, dropped = wiki_search("Cyberpunk", fetch=FakeFetch(wiki=wiki_payload(("Cyberpunk", "Cyberpunk 2077"))))
        self.assertEqual([r["title"] for r in records], ["Cyberpunk", "Cyberpunk 2077"])
        self.assertEqual(records[0]["url"], "https://en.wikipedia.org/wiki/Cyberpunk")
        self.assertEqual(records[0]["license"].split(" ")[0:2], ["CC", "BY-SA"])
        self.assertEqual(dropped, 0)

    def test_adult_pages_are_dropped(self):
        records, dropped = wiki_search("x", fetch=FakeFetch(wiki=wiki_payload(("Some Hentai Title",))))
        self.assertEqual((records, dropped), ([], 1))

    def test_missing_pages_skipped(self):
        data = {"query": {"pages": [{"title": "Nope", "missing": True}]}}
        self.assertEqual(wiki_search("x", fetch=FakeFetch(wiki=data))[0], [])


class AniListTests(unittest.TestCase):
    def setUp(self):
        self.records, self.dropped = anilist_search("Evangelion", fetch=FakeFetch(anilist=anilist_payload()))

    def test_adult_and_unflagged_titles_dropped(self):
        titles = [r["title"] for r in self.records]
        self.assertNotIn("Explicit Title", titles)
        self.assertNotIn("Unflagged", titles)
        self.assertEqual(self.dropped, 2)

    def test_spoilers_never_reach_the_model(self):
        text = " ".join(r["text"] for r in self.records)
        self.assertNotIn("Secret twist", text)
        self.assertIn("giant machine", text)

    def test_urls_are_built_by_the_server(self):
        self.assertEqual({r["url"] for r in self.records}, {"https://anilist.co/anime/30", "https://anilist.co/character/77"})

    def test_character_keeps_safe_appearances_when_another_work_is_adult(self):
        data = anilist_payload()
        person = data["data"]["people"]["characters"][0]
        person["media"]["nodes"].append({"id": 99, "isAdult": True, "genres": ["Hentai"],
                                          "title": {"english": "Excluded work"}})
        records, _ = anilist_search("Rei", fetch=FakeFetch(anilist=data))
        character = next(r for r in records if r["kind"] == "character")
        self.assertIn("Neon Genesis Evangelion", character["text"])
        self.assertNotIn("Excluded work", character["text"])

    def test_character_without_safe_appearances_is_excluded(self):
        data = anilist_payload()
        person = data["data"]["people"]["characters"][0]
        person["media"]["nodes"][0]["isAdult"] = True
        records, _ = anilist_search("Rei", fetch=FakeFetch(anilist=data))
        self.assertFalse(any(r["kind"] == "character" for r in records))


class FixtureTests(unittest.TestCase):
    def test_bundled_snapshots_carry_attribution_metadata(self):
        data = json.loads(SNAPSHOTS.read_text(encoding="utf-8"))
        self.assertEqual(data["license"], "CC-BY-SA-4.0")
        self.assertGreaterEqual(len(data["records"]), 12)
        for r in data["records"]:
            self.assertTrue(r["title"] and r["text"] and r["revid"] and r["retrieved"], r["title"])
            self.assertLessEqual(len(r["text"]), 1600)

    def test_lookup_by_title_alias_and_loose_match(self):
        fx = Fixtures(SNAPSHOTS)
        self.assertEqual(fx.search("cyberpunk")[0]["title"], "Cyberpunk")
        self.assertEqual(fx.search("Mecha anime and manga")[0]["title"], "Mecha anime and manga")
        self.assertEqual(fx.search("zzzz nothing")[0:1], [])
        self.assertTrue(all(r["fixture"] for r in fx.search("Isekai")))

    def test_missing_file_is_empty_not_fatal(self):
        self.assertEqual(Fixtures(Path(tempfile.gettempdir()) / "does-not-exist.json").search("x"), [])


class GatherTests(unittest.TestCase):
    def test_live_merges_and_numbers_sources(self):
        fetch = FakeFetch(wiki=wiki_payload(("Neon Genesis Evangelion",)), anilist=anilist_payload())
        records, notes = gather_evidence("Evangelion", mode="live", fetch=fetch)
        self.assertEqual([r["id"] for r in records], ["S%d" % i for i in range(1, len(records) + 1)])
        self.assertEqual({r["host"] for r in records}, {"en.wikipedia.org", "anilist.co"})
        self.assertEqual(notes["filtered_adult"], 2)
        self.assertEqual(notes["used"], "live")

    def test_auto_falls_back_to_snapshots_when_wikipedia_fails(self):
        fx = Fixtures(SNAPSHOTS)
        records, notes = gather_evidence("Cyberpunk", mode="auto", fixtures=fx, fetch=FakeFetch(fail=("wikipedia", "anilist")))
        self.assertTrue(records and all(r["fixture"] for r in records))
        self.assertEqual(notes["used"], "fixture")
        self.assertIn({"source": "wikipedia", "reason": "http_429"}, notes["failed"])

    def test_live_mode_never_uses_snapshots(self):
        records, notes = gather_evidence("Cyberpunk", mode="live", fixtures=Fixtures(SNAPSHOTS), fetch=FakeFetch(fail=("wikipedia", "anilist")))
        self.assertEqual((records, notes["used"]), ([], "none"))

    def test_fixture_mode_makes_no_network_calls(self):
        fetch = FakeFetch()
        records, _ = gather_evidence("Visual novel", mode="fixture", fixtures=Fixtures(SNAPSHOTS), fetch=fetch)
        self.assertTrue(records)
        self.assertEqual(fetch.calls, [])

    def test_record_text_is_budgeted(self):
        big = wiki_payload(tuple("Page %d" % i for i in range(4)), text="word " * 600)
        records, _ = gather_evidence("x", mode="live", fetch=FakeFetch(wiki=big))
        self.assertLessEqual(sum(len(r["text"]) for r in records), 12500)

    def test_model_view_hides_urls_and_internal_fields(self):
        records, _ = gather_evidence("Cyberpunk", mode="fixture", fixtures=Fixtures(SNAPSHOTS))
        shown = json.loads(evidence_for_model(records))
        self.assertEqual(set(shown[0]), {"id", "provider", "kind", "title", "text"})
        self.assertNotIn("http", evidence_for_model(records).split('"text"')[0])


if __name__ == "__main__":
    unittest.main()
