#!/usr/bin/env python3
"""Drive the running showcase in headless Chromium at 1024x600.

Usage: python scripts/browser_check.py http://127.0.0.1:8780 OUT_DIR

Walks the main judge flows (stage, gallery app, week calendar by voice and
touch, the voice-proposed change confirmed by touch, Ask the Three sample,
OTAKU Research Guide with the on-screen keyboard), saves a screenshot per
step and writes OUT_DIR/summary.json with console errors, page errors,
horizontal overflow and Hangul counts. Exits non-zero on any failure.

It taps one Research Guide topic. Without a Nebius key on the server that is
free (labelled source excerpts); with a key it is one bounded Nemotron call.
It never submits an Ask the Three story.
Requires: pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HANGUL = re.compile("[%s-%s]" % (chr(0xAC00), chr(0xD7A3)))


def main():
    base = sys.argv[1].rstrip("/")
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    report = {"base": base, "steps": [], "console_errors": [], "page_errors": []}
    failures = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        ctx = browser.new_context(viewport={"width": 1024, "height": 600}, has_touch=True)
        page = ctx.new_page()

        def on_console(msg):
            if msg.type == "error":
                report["console_errors"].append(f"{page.url} :: {msg.text}")
        page.on("console", on_console)
        page.on("pageerror", lambda e: report["page_errors"].append(str(e)))

        def scenario(name, wait=0.0, **extra):
            page.request.post(base + "/api/demo/scenario", data=dict(name=name, **extra))
            time.sleep(wait)

        def frame_text(frame):
            try:
                return frame.evaluate("document.body ? document.body.innerText : ''")
            except Exception:  # noqa: BLE001 - detached frames during navigation
                return ""

        def snap(name, check=None):
            time.sleep(0.4)
            path = out / f"{len(report['steps']) + 1:02d}-{name}.png"
            page.screenshot(path=str(path))
            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            hangul = sum(len(HANGUL.findall(frame_text(f))) for f in page.frames)
            step = {"name": name, "screenshot": path.name, "overflow": overflow, "hangul": hangul}
            if check is not None:
                ok, detail = check()
                step.update(ok=ok, detail=detail)
                if not ok:
                    failures.append(f"{name}: {detail}")
            if overflow:
                failures.append(f"{name}: horizontal overflow")
            if hangul:
                failures.append(f"{name}: {hangul} Hangul characters visible")
            report["steps"].append(step)
            return step

        # 1. Kiosk at native size: renderer + OTAKU app.
        page.goto(base + "/web/index.html?profile=otaku")
        page.wait_for_function("window.jarvisExhibition && window.jarvisExhibition.galleryVisible", timeout=15000)
        gallery = page.frame_locator("#otaku-en-frame")
        gallery.locator("body").wait_for(timeout=10000)
        time.sleep(2.5)
        snap("kiosk-gallery", lambda: (True, "OTAKU app visible over renderer"))

        # 2. Simulated voice turn: renderer wake wave + caption, gallery app hidden.
        scenario("voice_turn", wait=2.3)
        snap("voice-listening-thinking")
        time.sleep(3.2)
        snap("voice-speaking-caption", lambda: (
            bool(page.evaluate("document.querySelector('.caption-line').innerText.trim().length > 0")),
            "caption text rendered"))
        time.sleep(4.5)

        # 3. Week calendar by voice, then touch selection and voice navigation.
        scenario("week_open", wait=3.5)
        snap("week-open", lambda: (
            page.evaluate("window.jarvisWeekCalendar.isOpen") and
            page.locator("#week-calendar .wk-bar").count() == 7, "seven slats open"))
        bar = page.locator("#week-calendar .wk-bar").nth(4)
        bar.tap()
        time.sleep(0.6)
        snap("week-touch-select", lambda: (
            page.evaluate("Boolean(window.jarvisWeekCalendar.selectedDate)"),
            "selected " + str(page.evaluate("window.jarvisWeekCalendar.selectedDate"))))
        scenario("week_next", wait=1.5)
        snap("week-next", lambda: (
            page.evaluate("window.jarvisWeekCalendar.weekStart") > page.evaluate(
                "(function(){var d=new Date(Date.now()+9*3600e3);var w=(d.getUTCDay()+6)%7;"
                "d.setUTCDate(d.getUTCDate()-w);return d.toISOString().slice(0,10);})()"),
            "weekStart " + str(page.evaluate("window.jarvisWeekCalendar.weekStart"))))
        scenario("week_skin", wait=1.8, skin="moonlight")
        snap("week-skin-moonlight", lambda: (page.evaluate("window.jarvisWeekCalendar.skin") == "moonlight", "skin"))
        scenario("week_skin", wait=1.8, skin="riso")
        scenario("week_focus", wait=3.0)
        snap("week-voice-focus")
        time.sleep(4)
        scenario("week_move", wait=2.8)
        snap("week-voice-proposal", lambda: (
            page.locator('#week-calendar .wk-bar[data-ask="update"]').count() == 1, "proposal on Thursday"))
        page.locator('#week-calendar .wk-bar[data-ask="update"] .wk-btn[data-choice="confirm"]').tap()
        time.sleep(1.6)
        snap("week-touch-confirm", lambda: (
            "Moved to" in page.locator("#week-calendar").inner_text(), "confirmation result shown"))
        time.sleep(4)
        scenario("week_close", wait=1.5)
        page.request.post(base + "/api/demo/reset")
        time.sleep(1)

        # 4. Ask the Three opened the way the voice tool opens it.
        scenario("ask_three", wait=9)
        ask = page.frame_locator("#ask-frame")
        ask.locator("body").wait_for(timeout=10000)
        time.sleep(1.5)
        snap("ask-open", lambda: (page.evaluate("document.getElementById('ask-overlay').dataset.state") == "open",
                                  "overlay open"))
        frame = page.frame(name=None, url=re.compile(r"/ask-en/"))
        report["ask_text_sample"] = frame_text(frame)[:400] if frame else ""
        # Close through the app's own control (postMessage to the kiosk).
        page.evaluate("window.frames[0] && 0")
        page.evaluate("document.getElementById('ask-frame').contentWindow.postMessage({type:'ask-three-close'}, location.origin)")
        page.evaluate("""window.dispatchEvent(new MessageEvent('message', {origin: location.origin,
            source: document.getElementById('ask-frame').contentWindow, data: {type: 'ask-three-close'}}))""")
        time.sleep(1.2)
        snap("ask-closed", lambda: (page.evaluate("document.getElementById('ask-overlay').dataset.state") == "closed",
                                    "overlay closed, gallery back"))

        # 5. OTAKU Research Guide through touch: details -> topic tag -> research,
        #    then the on-screen keyboard. Without a Nebius key the app shows
        #    labelled source excerpts; with one, a topic tap is one Nemotron call.
        g = page.frame(url=re.compile(r"/otaku-en/"))
        g.wait_for_selector("#info-open")
        page.touchscreen.tap(512, 220)   # first touch wakes the auto-hidden controls
        time.sleep(0.5)
        g.locator("#info-open").tap()
        time.sleep(1.0)
        snap("otaku-details-tags", lambda: (g.evaluate("!document.getElementById('info').hidden"), "details open"))
        held = page.evaluate("window.jarvisOverlays.holders.slice()")
        report["overlay_holders_during_details"] = held
        topic = g.locator("#info-topics button").first
        report["topic"] = topic.inner_text()
        topic.tap()
        deadline = time.time() + 150   # the gallery's CSP forbids wait_for_function's eval
        while time.time() < deadline:
            text = g.evaluate("document.getElementById('research').innerText")
            if re.search(r"Sources|No matching|could not|failed", text, re.I) and \
                    not re.search(r"Searching|Finding|Writing|Reading", text[:200]):
                break
            time.sleep(1)
        time.sleep(1.5)
        research_text = g.evaluate("document.getElementById('research').innerText")
        report["research_text_sample"] = research_text[:600]
        snap("otaku-research-result", lambda: (len(research_text) > 80, "research page rendered"))
        g.locator("#research .rs-body, #research article, #research").first.evaluate(
            "e => { const s = document.querySelector('#research [class*=sources], #research ol'); if (s) s.scrollIntoView(); }")
        time.sleep(0.6)
        snap("otaku-research-sources")
        field = g.locator("#research input").first
        page.touchscreen.tap(512, 300)
        field.tap()
        time.sleep(0.6)
        snap("otaku-research-keyboard", lambda: (
            g.evaluate("!document.querySelector('#research .rs-keyboard').hidden"), "touch keyboard visible"))
        g.locator('#research .rs-key[data-key="shift"]').tap()
        for key in "cyberpunk":
            g.locator(f'#research .rs-key[data-key="{key}"]').first.tap()
        report["typed_query"] = field.input_value()
        if report["typed_query"] != "Cyberpunk":
            failures.append("touch keyboard typed %r" % report["typed_query"])
        snap("otaku-keyboard-typed")
        g.locator('#research .rs-key[data-key="hide"]').tap()
        g.locator("#research .rs-close").first.tap()
        time.sleep(1.0)
        snap("otaku-closed", lambda: (
            "otaku-en-research" not in page.evaluate("window.jarvisOverlays.holders.slice()"),
            "research lease released"))
        browser.close()

    report["failures"] = failures + [f"console: {e}" for e in report["console_errors"]] + \
        [f"pageerror: {e}" for e in report["page_errors"]]
    report["result"] = "PASS" if not report["failures"] else "FAIL"
    (out / "summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("result", "failures")}, indent=2))
    sys.exit(0 if report["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
