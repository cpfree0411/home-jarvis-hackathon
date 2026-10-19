#!/usr/bin/env python3
"""Drive a running server through one full story: text -> summary -> three votes -> reveal.

Checks the embargo on every poll and that every returned string is English.
Usage: python scripts/smoke_e2e.py http://127.0.0.1:8794/ [--sample haircut] [--show-text]
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

HANGUL = re.compile("[%s-%s]" % (chr(0xAC00), chr(0xD7AF)))


def origin_of(url):
    """scheme://host[:port] only, so a path-prefix proxy (/ask-en/) still matches."""
    u = urllib.parse.urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def call(base, path, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json", "Origin": origin_of(base)})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--sample", default="haircut")
    ap.add_argument("--show-text", action="store_true")
    ap.add_argument("--require-live", action="store_true", help="require all three judges to complete live")
    args = ap.parse_args()
    base = args.base.rstrip("/") + "/"
    cfg = call(base, "api/config")
    sample = next(s for s in cfg["samples"] if s["id"] == args.sample)
    sid = call(base, "api/stories", {"source": "sample", "sample_id": sample["id"]})["id"]
    call(base, f"api/stories/{sid}/text", {"text": sample["text"]})
    t0 = time.monotonic()
    while (story := call(base, f"api/stories/{sid}"))["status"] == "ORGANIZING":
        if time.monotonic() - t0 > 200:
            print(json.dumps({"E2E": "FAIL", "stage": "organizer timeout"}))
            return 1
        time.sleep(0.5)
    if story["status"] != "REVIEW":
        print(json.dumps({"E2E": "FAIL", "stage": "organize", "error": story.get("error")}))
        return 1
    organize_s = round(time.monotonic() - t0, 1)
    call(base, f"api/stories/{sid}/approve", {})
    t1, polls, leaks = time.monotonic(), 0, 0
    while True:
        story = call(base, f"api/stories/{sid}")
        polls += 1
        if story["panel"]["status"] == "REVEALED":
            break
        text = json.dumps(story["panel"])
        leaks += any(k in text for k in ("choice", "reasoning", "strength"))
        if time.monotonic() - t1 > 400:
            print(json.dumps({"E2E": "FAIL", "stage": "panel timeout"}))
            return 1
        time.sleep(1)
    panel = story["panel"]
    strings = json.dumps({"organized": story["organized"], "panel": panel}, ensure_ascii=False)
    completed = all(r["status"] == "COMPLETED" for r in panel["members"].values())
    live_ok = not args.require_live or panel["aggregate"]["live_votes"] == 3
    summary = {
        "E2E": "PASS" if completed and live_ok and not leaks and not HANGUL.search(strings) else "FAIL",
        "story": sid, "organizer": story["organizer"], "organize_s": organize_s,
        "panel_s": round(time.monotonic() - t1, 1), "waiting_polls": polls - 1, "embargo_leaks": leaks,
        "hangul_chars": len(HANGUL.findall(strings)),
        "seats": {m: {k: r.get(k) for k in ("status", "provider", "model", "live", "choice", "strength", "error")}
                  for m, r in panel["members"].items()},
        "aggregate": panel["aggregate"],
    }
    print(json.dumps(summary, indent=1))
    if args.show_text:
        print(json.dumps({"organized": story["organized"],
                          "answers": {m: {k: r.get(k) for k in ("reasoning", "other_side_credit", "suggestion")}
                                      for m, r in panel["members"].items()}}, indent=1, ensure_ascii=False))
    return 0 if summary["E2E"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
