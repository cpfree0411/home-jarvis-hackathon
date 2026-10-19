import time
import unittest

from otaku_gallery.errors import ResearchError
from otaku_gallery.research import ResearchManager, SCHEMA, PROMPT, build_page, evidence_only_page
from tests.helpers import StubWriter, good_draft, sample_records


class BuildPageTests(unittest.TestCase):
    def build(self, **over):
        return build_page("Cyberpunk", good_draft(**over), sample_records(), {})

    def test_grounded_page_is_verified_and_cited(self):
        page = self.build()
        self.assertEqual(page["status"], "answered")
        self.assertTrue(page["overview_verified"])
        self.assertTrue(all(s["verified"] for s in page["sections"] + page["facts"]))
        self.assertEqual(page["unverified_count"], 0)
        self.assertEqual(page["confidence"], "high")
        self.assertEqual([s["id"] for s in page["sources"] if s["cited"]], ["S1"])

    def test_invented_year_is_flagged_not_dropped(self):
        page = self.build(overview="Cyberpunk is a subgenre of science fiction that began in 1962.")
        self.assertFalse(page["overview_verified"])
        self.assertIn("1962", page["overview"])  # still shown, with a caveat
        self.assertEqual(page["confidence"], "medium")  # downgraded from high
        self.assertIn("could not be matched", page["limits"])

    def test_invented_name_is_flagged(self):
        page = self.build(sections=[{"heading": "People", "body": "The genre was shaped by Philip Dick and Yoko Kanno.", "source_ids": ["S1"]}])
        self.assertFalse(page["sections"][0]["verified"])

    def test_name_found_in_other_record_gains_that_citation(self):
        records = sample_records() + [{**sample_records("Neuromancer is a 1984 novel by William Gibson.")[0], "id": "S2", "title": "Neuromancer"}]
        draft = good_draft(sections=[{"heading": "Origins", "body": "William Gibson wrote Neuromancer.", "source_ids": ["S1"]}])
        page = build_page("Cyberpunk", draft, records, {})
        self.assertTrue(page["sections"][0]["verified"])
        self.assertEqual(page["sections"][0]["source_ids"], ["S1"])  # Gibson is in S1's own text here

    def test_unknown_source_ids_are_ignored_and_flagged(self):
        page = self.build(overview_source_ids=["S9", "http://evil.example"])
        self.assertEqual(page["overview_source_ids"], [])
        self.assertFalse(page["overview_verified"])

    def test_model_supplied_urls_never_become_links(self):
        page = self.build(related=[{"name": "Evil", "relation": "see http://evil.example", "source_ids": ["S1"]}])
        self.assertTrue(all(s["url"].startswith("https://en.wikipedia.org/") for s in page["sources"]))

    def test_unsafe_and_age_flag(self):
        self.assertEqual(self.build(status="unsafe"), {"status": "unsafe"})
        self.assertEqual(self.build(age_appropriate=False), {"status": "unsafe"})
        self.assertEqual(self.build(overview="This is hentai."), {"status": "unsafe"})

    def test_answered_without_content_is_rejected(self):
        with self.assertRaises(ResearchError) as cm:
            self.build(overview="", sections=[])
        self.assertEqual(cm.exception.code, "ungrounded")

    def test_ambiguous_needs_candidates(self):
        with self.assertRaises(ResearchError):
            self.build(status="ambiguous", candidates=[])
        page = self.build(status="ambiguous", candidates=[{"label": "Cyberpunk (genre)", "note": "The genre", "search_query": "Cyberpunk genre", "source_ids": ["S1"]}])
        self.assertEqual(page["candidates"][0]["query"], "Cyberpunk genre")

    def test_not_found_clears_content(self):
        page = self.build(status="not_found")
        self.assertEqual((page["overview"], page["sections"], page["facts"]), ("", [], []))

    def test_malformed_drafts(self):
        for bad in (None, [], {"status": "answered"}, good_draft(status="bogus"), good_draft(sections="x")):
            with self.assertRaises(ResearchError):
                build_page("q", bad, sample_records(), {})

    def test_evidence_only_page(self):
        page = evidence_only_page(sample_records(), "nebius_timeout")
        self.assertEqual(page["status"], "evidence_only")
        self.assertIn("too long", page["reason_message"])
        self.assertIn("verbatim", page["limits"])


class PromptTests(unittest.TestCase):
    def test_prompt_is_english_and_has_no_private_context(self):
        self.assertTrue(PROMPT.isascii())
        for word in ("wallpaper", "household", "living room"):
            self.assertNotIn(word, PROMPT.lower())
        self.assertIn("{query}", PROMPT)
        self.assertIn("{evidence}", PROMPT)

    def test_schema_fields_are_english(self):
        props = SCHEMA["properties"]
        self.assertIn("overview", props)
        self.assertEqual(set(SCHEMA["required"]), set(props))


def make_manager(writer, records=None, **kw):
    from otaku_gallery.evidence import Fixtures  # noqa: F401
    recs = sample_records() if records is None else records

    def gather(query, cancelled=None):
        return [dict(r) for r in recs], {"failed": [], "filtered_adult": 0, "used": "live"}
    return ResearchManager(writer, gather=gather, **kw)


def wait(manager, view, timeout=5):
    end = time.monotonic() + timeout
    while view["status"] in ("queued", "running") and time.monotonic() < end:
        time.sleep(0.02)
        view = manager.get(view["id"])
    return view


class ManagerTests(unittest.TestCase):
    def test_full_flow_with_usage_and_timing(self):
        writer = StubWriter()
        m = make_manager(writer)
        view = wait(m, m.start("Cyberpunk", context={"item_id": "a", "title": "A", "topic": "Cyberpunk"}))
        self.assertEqual(view["status"], "done")
        self.assertEqual(view["page"]["status"], "answered")
        self.assertEqual(view["page"]["model"], "nvidia/Nemotron-3-Ultra-550b-a55b")
        self.assertEqual(view["page"]["usage"]["total_tokens"], 30)
        self.assertEqual(view["context"]["topic"], "Cyberpunk")
        self.assertIn("evidence_ms", view["timings"])
        self.assertEqual(writer.calls[0][0], "Cyberpunk")

    def test_writer_error_degrades_to_source_excerpts(self):
        m = make_manager(StubWriter(error="nebius_key_unavailable"))
        view = wait(m, m.start("Cyberpunk"))
        self.assertEqual(view["page"]["status"], "evidence_only")
        self.assertEqual(view["page"]["reason"], "nebius_key_unavailable")
        self.assertIn("NEBIUS_API_KEY", view["page"]["reason_message"])

    def test_empty_and_adult_queries_never_reach_the_writer(self):
        writer = StubWriter()
        m = make_manager(writer)
        self.assertEqual(m.start("   ")["page"]["status"], "needs_query")
        self.assertEqual(m.start("hentai")["page"]["status"], "unsafe")
        self.assertEqual(writer.calls, [])

    def test_no_sources_is_not_found_without_model_call(self):
        writer = StubWriter()
        m = make_manager(writer, records=[])
        view = wait(m, m.start("zzz"))
        self.assertEqual(view["page"]["status"], "not_found")
        self.assertEqual(writer.calls, [])

    def test_cache_hit_skips_the_model_and_refresh_bypasses(self):
        writer = StubWriter()
        m = make_manager(writer)
        wait(m, m.start("Cyberpunk"))
        time.sleep(2.1)  # past the minimum interval between runs
        again = m.start("cyberpunk")
        self.assertTrue(again["cached"])
        self.assertEqual(len(writer.calls), 1)
        time.sleep(0.1)
        refreshed = wait(m, m.start("cyberpunk", refresh=True))
        self.assertFalse(refreshed["cached"])
        self.assertEqual(len(writer.calls), 2)

    def test_rate_limit(self):
        m = make_manager(StubWriter(), cache_ttl=0)
        wait(m, m.start("one"))
        view = m.start("two")  # inside the minimum interval
        self.assertEqual(view["page"]["status"], "rate_limited")
        self.assertGreaterEqual(view["retry_after"], 1)

    def test_cancel_stops_the_writer_and_hides_late_results(self):
        writer = StubWriter(delay=2.0)
        m = make_manager(writer)
        view = m.start("slow")
        time.sleep(0.2)
        cancelled = m.cancel(view["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        time.sleep(0.4)
        self.assertEqual(m.get(view["id"])["status"], "cancelled")
        self.assertIsNone(m.cancel("nope"))

    def test_newest_search_supersedes_and_duplicates_are_idempotent(self):
        writer = StubWriter(delay=0.8)
        now = [100.0]
        m = make_manager(writer, cache_ttl=0, rate_max_runs=50, clock=lambda: now[0])
        first = m.start("alpha", request_id="r1")
        self.assertEqual(m.start("alpha", request_id="r1")["id"], first["id"])
        self.assertEqual(m.start("alpha")["id"], first["id"])
        now[0] += 5  # past the minimum interval between runs
        second = m.start("beta")
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(m.get(first["id"])["status"], "cancelled")
        wait(m, second)

    def test_disabled(self):
        m = make_manager(StubWriter(), enabled=False)
        with self.assertRaises(ResearchError) as cm:
            m.start("x")
        self.assertEqual(cm.exception.code, "research_disabled")


if __name__ == "__main__":
    unittest.main()
