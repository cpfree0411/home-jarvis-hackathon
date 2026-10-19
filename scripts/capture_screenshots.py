#!/usr/bin/env python3
"""Capture the README screenshots from a running showcase.

Usage: python scripts/capture_screenshots.py http://127.0.0.1:8780 assets/screenshots

Uses only fictional sample data. If the server has a Nebius key, the Research
Guide shot is one real Nemotron call and the Ask the Three shot reopens the
newest saved verdict (run scripts/smoke_e2e.py first to create one).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    base, out = sys.argv[1].rstrip("/"), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)

    def demo(page, name, wait, **kw):
        page.request.post(base + "/api/demo/scenario", data=dict(name=name, **kw))
        time.sleep(wait)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])

        # Stage page: what a judge sees first.
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.request.post(base + "/api/demo/reset")
        page.goto(base + "/")
        time.sleep(5)
        page.screenshot(path=str(out / "stage-desktop.png"))
        page.close()

        ctx = browser.new_context(viewport={"width": 1024, "height": 600}, has_touch=True)
        page = ctx.new_page()
        page.goto(base + "/web/index.html?profile=otaku")
        page.wait_for_function("window.jarvisExhibition && window.jarvisExhibition.galleryVisible")
        time.sleep(4)
        page.screenshot(path=str(out / "kiosk-gallery.png"))

        demo(page, "voice_turn", 5.6)
        page.screenshot(path=str(out / "kiosk-voice-caption.png"))
        time.sleep(5)

        demo(page, "week_open", 10)   # let the spoken reply finish first
        page.screenshot(path=str(out / "week-riso.png"))
        for skin in ("tape", "moonlight"):
            demo(page, "week_skin", 2.2, skin=skin)
            page.screenshot(path=str(out / f"week-{skin}.png"))
        demo(page, "week_skin", 2.2, skin="riso")
        demo(page, "week_move", 3)
        page.screenshot(path=str(out / "week-voice-proposal.png"))
        demo(page, "week_close", 1.5)
        page.request.post(base + "/api/demo/reset")
        time.sleep(1)

        # Ask the Three: newest saved verdict, reopened read-only from the archive.
        page.reload()   # a fresh kiosk, as after the household's own idle timeout
        page.wait_for_function("window.jarvisExhibition && window.jarvisExhibition.galleryVisible")
        time.sleep(2)
        demo(page, "ask_three", 8)
        ask = None
        for _ in range(40):
            ask = next((f for f in page.frames if "/ask-en/" in f.url), None)
            if ask:
                break
            page.wait_for_timeout(500)   # time.sleep would not pump frame events
        ask.wait_for_selector("body")
        time.sleep(1)
        page.screenshot(path=str(out / "ask-home.png"))
        try:
            ask.locator("#past").click()
            time.sleep(1.5)
            ask.locator(".archive-card").first.click()
            time.sleep(2.5)
            page.screenshot(path=str(out / "ask-verdict.png"))
        except Exception as exc:  # noqa: BLE001 - archive may be empty in demo mode
            print("ask verdict skipped:", exc)
        page.evaluate("""window.dispatchEvent(new MessageEvent('message', {origin: location.origin,
            source: document.getElementById('ask-frame').contentWindow, data: {type: 'ask-three-close'}}))""")
        time.sleep(1.5)

        # OTAKU Research Guide by touch.
        g = next(f for f in page.frames if "/otaku-en/" in f.url)
        page.touchscreen.tap(512, 220)
        time.sleep(0.5)
        g.locator("#info-open").tap()
        time.sleep(1.2)
        page.screenshot(path=str(out / "otaku-details.png"))
        g.locator("#info-topics button").first.tap()
        deadline = time.time() + 150
        while time.time() < deadline:
            if g.evaluate("!!document.querySelector('#research .rs-sources')"):
                break
            page.wait_for_timeout(1000)
        time.sleep(1.5)
        page.screenshot(path=str(out / "otaku-research.png"))
        # Scroll the Research Guide's own scroller (scrollIntoView would also
        # shift the iframe document and expose the gallery underneath).
        g.evaluate("""() => { const el = document.querySelector('#research .rs-sources');
            let p = el.parentElement; while (p && p.scrollHeight <= p.clientHeight + 1) p = p.parentElement;
            if (p) p.scrollTop = el.offsetTop - 140; window.scrollTo(0, 0); }""")
        time.sleep(0.8)
        page.screenshot(path=str(out / "otaku-sources.png"))
        g.evaluate("""() => { document.querySelectorAll('#research *').forEach(e => { if (e.scrollTop) e.scrollTop = 0; });
            window.scrollTo(0, 0); }""")
        page.touchscreen.tap(512, 300)
        g.locator("#research input").first.tap()
        time.sleep(0.8)
        page.screenshot(path=str(out / "otaku-keyboard.png"))
        browser.close()
    print("saved to", out)


if __name__ == "__main__":
    main()
