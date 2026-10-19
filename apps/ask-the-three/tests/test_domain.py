import json

import pytest

from ask_three_en import ai, config
from ask_three_en.domain import PANEL, aggregate, organized, panel_result, presentation_reversed, public_panel
from ask_three_en.samples import BY_ID, SAMPLES

ORGANIZED = BY_ID["haircut"]["organized"]
RESULT = {"choice": "A", "strength": "LEAN", "reasoning": "A is a little more convincing as described.",
          "other_side_credit": "B has a fair point too.", "suggestion": "Agree on a shared rule."}


def test_schema_and_normalization():
    assert organized(json.dumps(ORGANIZED)) == ORGANIZED
    assert organized("```json\n" + json.dumps(ORGANIZED) + "\n```") == ORGANIZED
    with pytest.raises(ValueError):
        organized(json.dumps({**ORGANIZED, "facts": "an extra field"}))
    with pytest.raises(ValueError):
        organized("Sure! Here is the summary: {}")
    assert panel_result(json.dumps(RESULT), False)["choice"] == "A"
    assert panel_result(json.dumps(RESULT), True)["choice"] == "B"
    for bad in ("DRAW", "BOTH", "ABSTAIN"):
        with pytest.raises(ValueError):
            panel_result(json.dumps({**RESULT, "choice": bad}), False)
    with pytest.raises(ValueError):
        panel_result(json.dumps({**RESULT, "strength": "MAYBE"}), False)


def test_exactly_one_reversed_seat_per_story():
    for i in range(50):
        assert sum(presentation_reversed(f"story-{i}", m) for m in PANEL) == 1
    prompt = ai.panel_prompt(ORGANIZED, True)
    assert json.dumps({"A": ORGANIZED["side_b"]})[1:-1] in prompt
    assert json.dumps({"B": ORGANIZED["side_a"]})[1:-1] in prompt


def test_aggregation_and_embargo():
    rows = [{"member": m, "status": "PENDING", "live": 1} for m in PANEL]
    rows[0].update({"status": "COMPLETED", **RESULT})
    for completed in (1, 2):
        if completed == 2:
            rows[1].update({"status": "COMPLETED", **{**RESULT, "choice": "B"}})
        public = public_panel(rows)
        assert public == {"status": "WAITING", "members": list(PANEL)}
        assert "choice" not in json.dumps(public) and "reasoning" not in json.dumps(public)
    rows[2].update({"status": "COMPLETED", **RESULT})
    assert public_panel(rows)["aggregate"] == {"winner": "A", "votes_a": 2, "votes_b": 1, "live_votes": 3}
    rows[2] = {"member": "claude", "status": "FAILED", "error": "timeout", "live": 1}
    assert public_panel(rows)["members"]["claude"]["status"] == "FAILED"
    assert public_panel(rows)["aggregate"] == {"winner": None, "votes_a": 1, "votes_b": 1, "live_votes": 2}
    assert aggregate({}) == {"winner": None, "votes_a": 0, "votes_b": 0, "live_votes": 0}


def test_repair_once(monkeypatch):
    settings = config.load()
    settings.seat_provider["nemotron"] = "nebius"
    calls = []

    def fake(_s, member, prompt):
        calls.append(prompt)
        return "not json" if len(calls) == 1 else json.dumps(RESULT)
    monkeypatch.setattr(ai, "_call", fake)
    assert ai.run_member(settings, "nemotron", ORGANIZED, False)["choice"] == "A"
    assert len(calls) == 2 and calls[1].endswith(ai.REPAIR)
    monkeypatch.setattr(ai, "_call", lambda *_: "not json")
    with pytest.raises(ValueError):
        ai.run_member(settings, "nemotron", ORGANIZED, False)


def test_samples_are_complete_and_valid():
    assert BY_ID["haircut"]["teaser"] == "The haircut question"
    for sample in SAMPLES:
        assert organized(json.dumps(sample["organized"])) == sample["organized"]
        for member in PANEL:
            answer = json.dumps(sample["fixture"][member])
            assert panel_result(answer, False) == sample["fixture"][member]
