#!/usr/bin/env python3
"""The real app on a throwaway DB with gated demo judges and a scripted transcriber.

For UI screenshots and browser QA only: no provider is called and no key is read.
Usage: python scripts/ui_fixture_server.py PORT TMPDIR
"""
import asyncio
import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

port, tmp = int(sys.argv[1]), Path(sys.argv[2])
tmp.mkdir(parents=True, exist_ok=True)
for name in ("NEBIUS_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(name, None)
os.environ.update({"ASK_THREE_STATE": str(tmp / "state"), "ASK_THREE_DB": str(tmp / "fixture.sqlite3"),
                   "ASK_THREE_PORT": str(port)})

import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402

from ask_three_en import ai, config  # noqa: E402
from ask_three_en import app as module  # noqa: E402
from ask_three_en.domain import PANEL  # noqa: E402
from ask_three_en.samples import BY_ID, fixture_answer  # noqa: E402

settings = config.load()
settings.stt = "gemini-live"  # scripted below; lets the recording screen be captured
gates: dict[str, threading.Event] = {}
outcomes: dict[str, str] = {}
SPOKEN = ("So my girlfriend Maya got a really dramatic haircut on Saturday. She asked me if I honestly liked it, "
          "and I said it was bold and I needed a day to get used to it.").split()


class ScriptedTranscriber:
    MODEL = "scripted-fixture"

    def __init__(self, language="en-US"):
        pass

    async def stream(self, audio):
        words, done = [], asyncio.Event()

        async def drain():
            async for _ in audio:
                pass
            done.set()
        task = asyncio.create_task(drain())
        for word in SPOKEN:
            if done.is_set():
                break
            words.append(word)
            yield {"type": "interim", "text": " ".join(words)}
            await asyncio.sleep(0.12)
        await done.wait()
        await task
        yield {"type": "complete", "text": " ".join(SPOKEN)}


module.GeminiTranscribeLive = ScriptedTranscriber


def gated_member(s, member, approved, reversed_order, sample_id=None, story_id=""):
    gates.setdefault(member, threading.Event()).wait(600)
    if outcomes.get(member) == "FAILED":
        raise RuntimeError("fixture failure")
    return fixture_answer(member, sample_id, story_id)


ai.run_member = gated_member
app = module.create_app(settings)
repo = app.state.repo


def seed(sample_id, outcome, days_ago, title=None):
    sample = BY_ID[sample_id]
    organized = dict(sample["organized"], title=title or sample["organized"]["title"])
    sid = repo.create("sample", sample_id)
    repo.set_transcript(sid, sample["text"])
    repo.set_organized(sid, organized, "prepared-sample")
    with sqlite3.connect(settings.db) as db:
        when = f"2026-10-{18 - days_ago:02d}T{14 + days_ago:02d}:30:00+00:00"
        db.execute("UPDATE stories SET status='REVEALED',approved_input=organizer_output,created_at=? WHERE id=?", (when, sid))
        for member in PANEL:
            if outcome.get(member) == "FAILED":
                db.execute("INSERT INTO panel_runs(story_id,member,status,provider,model,live,reversed_order,error) "
                           "VALUES(?,?,?,?,?,?,?,?)", (sid, member, "FAILED", "fixture", "demo-fixture", 0, 0, "fixture_failure"))
                continue
            a = sample["fixture"][member]
            db.execute("INSERT INTO panel_runs(story_id,member,status,provider,model,live,reversed_order,choice,strength,"
                       "reasoning,other_side_credit,suggestion) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (sid, member, "COMPLETED", "fixture", "demo-fixture", 0, 0, a["choice"], a["strength"],
                        a["reasoning"], a["other_side_credit"], a["suggestion"]))
    return sid


SEEDED = {
    "game": seed("game-night", {}, 5),
    "failed": seed("dinner-bill", {"gpt": "FAILED"}, 3),
    "long": seed("haircut", {}, 1, title="Honest or supportive about a dramatic new haircut that can't be undone, when she asked me straight away and was already nervous about it?"),
}


@app.post("/__fixture/outcomes")
async def fixture_outcomes(request: Request):
    outcomes.clear()
    outcomes.update(await request.json())
    gates.clear()
    return {"ok": True}


@app.post("/__fixture/release/{member}")
def fixture_release(member: str):
    gates.setdefault(member, threading.Event()).set()
    return {"ok": True}


@app.get("/__fixture/state/{sid}")
def fixture_state(sid: str):
    with repo.conn() as db:
        return {r["member"]: r["status"] for r in db.execute("SELECT member,status FROM panel_runs WHERE story_id=?", (sid,))}


@app.get("/__fixture/seeded")
def fixture_seeded():
    return SEEDED


print(json.dumps({"port": port, "seeded": SEEDED}), flush=True)
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
