#!/usr/bin/env python3
"""Browser smoke test + screenshots (needs: pip install playwright && playwright install chromium).

Default: offline. Evidence comes from the bundled Wikipedia snapshots and the model is
replaced by a clearly labelled stub writer, so no network call and no API credit is used.
--live: uses the real NebiusWriter (NEBIUS_API_KEY in the environment) and public fixtures. One paid
        call per run; a small call ledger file (--ledger) caps total reservations.
"""
import argparse
import json
import os
import sys
import time
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from otaku_gallery.app import build_app  # noqa: E402
from otaku_gallery.config import Config  # noqa: E402
from otaku_gallery.evidence import Fixtures, gather_evidence  # noqa: E402
from otaku_gallery.nebius import MODEL, NebiusWriter  # noqa: E402
from otaku_gallery.server import make_server, serve_in_thread  # noqa: E402
from scripts.model_smoke import BudgetedWriter, proof  # noqa: E402


class StubWriter:
    """Test-only writer: builds a schema-valid draft from the first evidence record's own sentences."""
    model = MODEL + " (STUB, offline test)"
    usage = {}

    def configured(self):
        return True

    def cancel(self):
        pass

    def write(self, query, records, timeout=35, cancelled=None):
        first = records[0]
        sentences = [s.strip() + "." for s in first["text"].replace("\n", " ").split(". ") if s.strip()][:4]
        sid = first["id"]
        draft = {"status": "answered", "entity_kind": "genre", "title": first["title"], "title_original": "",
                 "tagline": "Stub tagline from the cited excerpt.", "overview": " ".join(sentences[:2]),
                 "overview_source_ids": [sid], "primary_source_id": sid,
                 "sections": [{"heading": "From the source", "body": " ".join(sentences[2:4]) or sentences[0], "source_ids": [sid]}],
                 "facts": [{"label": "Topic", "value": first["title"], "source_ids": [sid]}],
                 "related": [], "candidates": [], "confidence": "medium",
                 "confidence_reason": "Offline stub used for the UI test.", "limits": "Stub output, not a model answer.",
                 "age_appropriate": True}
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        return draft, 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="real Nebius writer and public fixtures (one paid call)")
    ap.add_argument("--missing-key", action="store_true", help="test real source-excerpt fallback without a key")
    ap.add_argument("--ledger", type=Path, default=ROOT / "docs/validation/model-budget.json")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    ap.add_argument("--topic", default="cyberpunk", help="topic id of the first artwork to research")
    ap.add_argument("--summary", type=Path, help="write a JSON evidence summary here")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    config = Config.from_env()
    config = Config(**{**config.__dict__, "evidence_mode": "fixture"})
    if args.live:
        app = build_app(config, writer=BudgetedWriter(args.ledger))
        if not app.writer.configured():
            sys.exit("NEBIUS_API_KEY is not set in the environment")
    elif args.missing_key:
        app = build_app(config, writer=NebiusWriter(environ={}))
    else:
        config = Config(**{**config.__dict__, "evidence_mode": "fixture", "cache_ttl": 0})
        fixtures = Fixtures(config.root / "data" / "fixtures" / "wikipedia-snapshots.json")
        app = build_app(config, writer=StubWriter(), gather=partial(gather_evidence, mode="fixture", fixtures=fixtures))
    server = make_server(app, "127.0.0.1", 0)
    serve_in_thread(server)
    base = "http://127.0.0.1:%d/" % server.server_address[1]
    args.out.mkdir(parents=True, exist_ok=True)
    checks, summary = [], {"live": args.live, "base": "loopback ephemeral port"}
    terminal = {}

    def capture(response):
        if "/api/research/" in response.url and response.request.method == "GET":
            value = response.json()
            if value.get("status") == "done":
                terminal.update(value)

    def check(name, ok):
        checks.append((name, bool(ok)))
        print(("PASS " if ok else "FAIL ") + name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1024, "height": 600})
        page = ctx.new_page()
        page.on("response", capture)
        external = []
        page.on("request", lambda r: external.append(r.url) if not r.url.startswith(base) and not r.url.startswith("data:") else None)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "?autoplay=0")
        page.wait_for_selector("#app[data-state=ready]")
        page.wait_for_selector(".layer.is-active", state="attached")
        time.sleep(1.8)
        page.screenshot(path=str(args.out / "01-gallery-1024x600.png"))
        check("gallery shows first artwork title", page.inner_text("#cap-title") == "Rain Over Neon Row")
        check("no horizontal overflow at 1024x600", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        page.press("body", "ArrowRight")
        page.wait_for_selector("#counter:text-is('2 / 8')")
        check("next artwork via keyboard", page.inner_text("#counter").startswith("2 / 8"))
        page.press("body", "ArrowLeft")
        page.click("#fav")
        check("favorite persists in localStorage", "neon-rooftop-rain" in page.evaluate("localStorage.getItem('otaku-gallery-en:favorites')"))
        page.click("#info-open")
        page.wait_for_selector("#info:not([hidden])")
        time.sleep(0.5)
        page.screenshot(path=str(args.out / "02-details-and-tags-1024x600.png"))
        page.click("#filter-tags button:has-text('#cyberpunk')")
        check("tag filter narrows the view", page.inner_text("#counter").startswith("1 / 1"))
        page.click("#filter-tags button:has-text('All')")
        page.click("#info-close")
        page.click("#research-open")
        page.wait_for_selector("#research:not([hidden])")
        time.sleep(0.3)
        page.screenshot(path=str(args.out / "03-research-guide-intro-1024x600.png"))
        page.click(".rs-topics button:has-text('Cyberpunk')")
        started = time.time()
        page.wait_for_selector(".rs-article:not([hidden]) h1, .rs-article:not([hidden]) .rs-notice h2", timeout=90000)
        summary["ui_wall_s"] = round(time.time() - started, 2)
        time.sleep(0.4)
        page.screenshot(path=str(args.out / "04-research-result-1024x600.png"))
        text = page.inner_text(".rs-article")
        check("research page rendered", len(text) > 200)
        check("English UI has no Hangul text", not any("\uac00" <= c <= "\ud7a3" for c in page.inner_text("body")))
        check("source links come from allowlisted hosts", page.evaluate(
            "Array.from(document.querySelectorAll('.rs-sources a')).every(a => /^https:\\/\\/(en\\.wikipedia\\.org|anilist\\.co)\\//.test(a.href))"))
        if args.missing_key:
            check("honest missing-key fallback", "Source excerpts" in text and "NEBIUS_API_KEY" in text)
        else:
            check("model chip visible", "NVIDIA Nemotron 3 Ultra" in text)
        check("sources are present", page.locator(".rs-sources a").count() > 0)
        check("citation marker visible", page.locator(".rs-cite").count() > 0)
        check("no horizontal overflow in research view", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        page.locator(".rs-sources").evaluate("e => { const b = e.closest('.rs-body'); b.scrollTop += e.getBoundingClientRect().top - b.getBoundingClientRect().top; }")
        time.sleep(0.3)
        page.screenshot(path=str(args.out / "05-research-sources-1024x600.png"))
        page.press("body", "Escape")
        page.wait_for_selector("#research", state="hidden")
        check("closing the panel hides it", True)
        for name, size in (("desktop-1920x1080", (1920, 1080)), ("phone-390x844", (390, 844))):
            p2 = ctx.new_page()
            p2.set_viewport_size({"width": size[0], "height": size[1]})
            p2.goto(base + "?autoplay=0")
            p2.wait_for_selector("#app[data-state=ready]")
            time.sleep(1.8)
            p2.screenshot(path=str(args.out / ("06-gallery-%s.png" % name)))
            check("no horizontal overflow at %dx%d" % size, p2.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            p2.close()
        check("no third-party network requests", not external)
        check("no page errors", not errors)
        summary["external_requests"] = external
        browser.close()
    # Capture the UI's terminal poll; never submit a second paid request for proof.
    if args.live:
        view = terminal
        page_ = view.get("page") or {}
        summary.update(proof(app.writer))
        check("real model answered from cited evidence", page_.get("status") == "answered" and bool(app.writer.usage))
        summary.update(status=page_.get("status"), model=page_.get("model"), usage=page_.get("usage"),
                       timings=view.get("timings"), cached=view.get("cached"), unverified=page_.get("unverified_count"),
                       sources=[{k: s[k] for k in ("id", "provider", "title", "url", "cited")} for s in page_.get("sources", [])])
    summary["checks"] = [{"name": n, "pass": ok} for n, ok in checks]
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    server.shutdown()
    failed = [n for n, ok in checks if not ok]
    print("%d/%d checks passed" % (len(checks) - len(failed), len(checks)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
