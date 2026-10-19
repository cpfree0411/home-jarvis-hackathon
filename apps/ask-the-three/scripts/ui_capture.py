#!/usr/bin/env python3
"""1024x600 browser QA and screenshots (needs `pip install playwright && playwright install chromium`).

  fixture mode: python scripts/ui_capture.py fixture http://127.0.0.1:8799/ OUTDIR
      (against scripts/ui_fixture_server.py: every screen, gated judges, scripted voice)
  live mode:    python scripts/ui_capture.py live http://127.0.0.1:8794/ OUTDIR [--ask]
      (against a real server; --ask submits one typed synthetic story to the live judges)

Each screen is checked for horizontal overflow, any Hangul text, small touch targets,
fonts and console errors; results go to OUTDIR/qa-<mode>.json.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

mode, BASE, OUT = sys.argv[1], sys.argv[2].rstrip("/") + "/", Path(sys.argv[3])
ASK = "--ask" in sys.argv
OUT.mkdir(parents=True, exist_ok=True)
qa, errors = [], []
CUSTOM = ("My brother borrowed my car for the weekend and brought it back with the fuel light on. "
          "He says I never asked him to fill it up, so it's fine. I think refilling it is basic courtesy "
          "when you borrow someone's car. Which of us is being more reasonable?")

CHECK = """() => {
  const hangul = /[\\u1100-\\u11ff\\u3130-\\u318f\\uac00-\\ud7af]/g;
  const text = document.body.innerText;
  const small = [...document.querySelectorAll('button')].filter(b => {
    const r = b.getBoundingClientRect(); return r.width > 0 && (r.height < 50 || r.width < 50);
  }).map(b => b.textContent.trim().slice(0, 30));
  const doc = document.documentElement;
  return {hangul: (text.match(hangul) || []).length, overflow_x: doc.scrollWidth - doc.clientWidth,
          small_targets: small, hand_font: document.fonts.check('700 24px "Ask Hand"'),
          text_font: document.fonts.check('400 18px "Ask Text"'), chars: text.length};
}"""


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Origin": BASE.rstrip("/")})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=10).read())


def shot(page, name, settle=0.75):
    time.sleep(settle)
    page.screenshot(path=str(OUT / f"{name}.png"))
    info = page.evaluate(CHECK)
    info["screen"] = name
    qa.append(info)


def click(page, selector):
    page.click(selector)


def fixture(page):
    page.goto(BASE)
    page.wait_for_selector("#new")
    shot(page, "01-home-demo")
    click(page, "#new"); page.wait_for_selector("#sample"); shot(page, "02-setup")
    click(page, "#sample"); page.wait_for_selector("[data-sample]"); shot(page, "03-samples")
    click(page, "[data-sample=haircut]"); page.wait_for_selector("#use"); shot(page, "04-sample-read")
    click(page, "#edit"); page.wait_for_selector("#story"); shot(page, "05-typing")
    page.fill("#story", CUSTOM); shot(page, "06-typing-filled", 0.3)
    click(page, "#done"); page.wait_for_selector(".notice"); page.wait_for_selector("#retry", timeout=8000)
    shot(page, "07-error-no-key")
    click(page, "#retry"); page.wait_for_selector("#go")
    click(page, "#go"); page.wait_for_selector("#clock"); time.sleep(2.4); shot(page, "08-recording", 0.2)
    click(page, "#done"); shot(page, "09-wrapping-up", 0.15)
    page.wait_for_selector("#retry", timeout=8000); shot(page, "10-voice-error-no-key", 0.3)
    # Sample story, gated demo judges: embargo at 0/3, 1/3, 2/3.
    post("__fixture/outcomes", {})
    click(page, "#retry"); page.wait_for_selector("#sample")
    click(page, "#sample"); page.wait_for_selector("[data-sample=haircut]"); click(page, "[data-sample=haircut]")
    page.wait_for_selector("#use"); click(page, "#use")
    page.wait_for_selector(".notice"); shot(page, "11-organizing", 0.2)
    page.wait_for_selector("#approve", timeout=8000); shot(page, "12-review")
    click(page, "#approve"); page.wait_for_selector(".sealed-row"); shot(page, "13-waiting-0of3", 1.4)
    baseline = page.inner_html(".main")
    for i, member in enumerate(("nemotron", "gpt"), start=1):
        post(f"__fixture/release/{member}", {})
        time.sleep(2.6)
        same = page.inner_html(".main") == baseline
        qa.append({"screen": f"embargo-{i}of3", "dom_unchanged": same})
        shot(page, f"14-waiting-{i}of3", 0)
    post("__fixture/release/claude", {})
    page.wait_for_selector(".result-cards", timeout=8000); shot(page, "15-reveal-peeling", 0.25)
    shot(page, "16-reveal-demo", 1.2)
    for i, member in enumerate(("nemotron", "gpt", "claude")):
        click(page, f"[data-member={member}]"); page.wait_for_selector(".detail-body"); shot(page, f"17-detail-{member}-demo")
        click(page, "#back"); page.wait_for_selector(".result-cards")
    click(page, "#raw"); page.wait_for_selector(".transcript"); shot(page, "18-original-words")
    click(page, "#result"); click(page, "#home"); page.wait_for_selector("#past")
    click(page, "#past"); page.wait_for_selector(".archive-card"); shot(page, "19-archive-demo", 1.0)
    seeded = get("__fixture/seeded")
    page.click(f"[data-id='{seeded['failed']}']"); page.wait_for_selector(".result-cards"); shot(page, "20-reveal-one-failed")
    click(page, "[data-member=gpt]"); page.wait_for_selector(".detail-body"); shot(page, "21-detail-failed")
    click(page, "#back"); click(page, "#delete"); page.wait_for_selector("#cancel"); shot(page, "22-delete-confirm")
    click(page, "#cancel"); click(page, "#home"); click(page, "#past"); page.wait_for_selector(".archive-card")
    page.click(f"[data-id='{seeded['long']}']"); page.wait_for_selector(".result-cards"); shot(page, "23-reveal-long-title")


def live(page):
    page.goto(BASE)
    page.wait_for_selector("#new")
    shot(page, "L01-home-live")
    click(page, "#past"); page.wait_for_selector(".archive-card"); shot(page, "L02-archive-live", 1.0)
    if ASK:
        click(page, "#back"); click(page, "#new"); page.wait_for_selector("#type"); click(page, "#type")
        page.fill("#story", CUSTOM); shot(page, "L03-typing-live", 0.3)
        click(page, "#done"); page.wait_for_selector("#approve", timeout=60000); shot(page, "L04-review-live")
        click(page, "#approve"); page.wait_for_selector(".sealed-row"); shot(page, "L05-waiting-live", 1.2)
        page.wait_for_selector(".result-cards", timeout=400000); shot(page, "L06-reveal-peeling-live", 0.25)
        shot(page, "L07-reveal-live", 1.2)
    else:
        page.click(".archive-card"); page.wait_for_selector(".result-cards"); shot(page, "L07-reveal-live")
    for member in ("nemotron", "gpt", "claude"):
        click(page, f"[data-member={member}]"); page.wait_for_selector(".detail-body"); shot(page, f"L08-detail-{member}-live")
        click(page, "#back"); page.wait_for_selector(".result-cards")


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
    for motion in (["no-preference", "reduce"] if mode == "fixture" else ["no-preference"]):
        ctx = browser.new_context(viewport={"width": 1024, "height": 600}, device_scale_factor=1,
                                  reduced_motion=motion, permissions=["microphone"], locale="en-US")
        page = ctx.new_page()
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        if motion == "reduce":
            page.goto(BASE); page.wait_for_selector("#past"); page.click("#past"); page.wait_for_selector(".archive-card")
            page.click(".archive-card"); page.wait_for_selector(".result-cards"); shot(page, "24-reduced-motion-reveal", 0.4)
        else:
            (fixture if mode == "fixture" else live)(page)
        ctx.close()
    browser.close()

summary = {"mode": mode, "screens": len([q for q in qa if "hangul" in q]),
           "hangul_total": sum(q.get("hangul", 0) for q in qa),
           "max_overflow_x": max(q.get("overflow_x", 0) for q in qa),
           "small_targets": sorted({t for q in qa for t in q.get("small_targets", [])}),
           "fonts_ok": all(q.get("hand_font", True) and q.get("text_font", True) for q in qa),
           "embargo_dom_unchanged": [q["dom_unchanged"] for q in qa if "dom_unchanged" in q],
           "console_errors": errors}
(OUT / f"qa-{mode}.json").write_text(json.dumps({"summary": summary, "screens": qa}, indent=1))
print(json.dumps(summary, indent=1))
assert summary["screens"] > 0
assert summary["hangul_total"] == 0 and summary["max_overflow_x"] == 0
assert not summary["small_targets"] and summary["fonts_ok"]
assert all(summary["embargo_dom_unchanged"]) and not summary["console_errors"]
