"""Pure story/panel rules: schemas, A/B order, aggregation and the embargo."""
from __future__ import annotations

import hashlib
import json
import re

PANEL = ("nemotron", "gpt", "claude")
SEAT = {m: i for i, m in enumerate(PANEL)}
STRENGTH = {"CLOSE", "LEAN", "STRONG"}
TERMINAL = ("COMPLETED", "FAILED")
PUBLIC_FIELDS = ("status", "provider", "model", "live", "choice", "strength", "reasoning",
                 "other_side_credit", "suggestion", "error")


def parse_object(raw: str) -> dict:
    """Accept one object or one fenced object; reject prose and ambiguous objects."""
    text = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S | re.I)
    if match:
        text = match.group(1)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _text(value, limit: int, low: int = 2) -> str:
    if not isinstance(value, str) or not low <= len(value.strip()) <= limit:
        raise ValueError("text bounds")
    return value.strip()


def organized(raw: str) -> dict:
    value = parse_object(raw)
    if set(value) != {"title", "context", "subject", "entities", "side_a", "side_b"}:
        raise ValueError("organizer fields")
    for key, limit in (("title", 120), ("context", 900), ("subject", 200)):
        value[key] = _text(value[key], limit)
    if not isinstance(value["entities"], list) or len(value["entities"]) > 12:
        raise ValueError("organizer entities")
    for entity in value["entities"]:
        if not isinstance(entity, dict) or set(entity) != {"name", "role"}:
            raise ValueError("organizer entity")
        for key in ("name", "role"):
            entity[key] = _text(entity[key], 80, 1)
    for side in ("side_a", "side_b"):
        part = value[side]
        if not isinstance(part, dict) or set(part) != {"label", "position"}:
            raise ValueError(f"organizer {side}")
        part["label"] = _text(part["label"], 80)
        part["position"] = _text(part["position"], 900)
    return value


def panel_result(raw: str, reversed_order: bool) -> dict:
    value = parse_object(raw)
    if set(value) != {"choice", "strength", "reasoning", "other_side_credit", "suggestion"}:
        raise ValueError("panel fields")
    choice = value["choice"]
    if choice not in ("A", "B"):
        raise ValueError("choice")
    if value["strength"] not in STRENGTH:
        raise ValueError("strength")
    for key in ("reasoning", "other_side_credit", "suggestion"):
        value[key] = _text(value[key], 900)
    value["choice"] = ("B" if choice == "A" else "A") if reversed_order else choice
    return value


def presentation_reversed(story_id: str, member: str) -> bool:
    """Stable per story: exactly one seat sees B first, so position bias can't sweep the panel."""
    offset = int(hashlib.sha256(story_id.encode()).hexdigest(), 16) % 3
    return SEAT[member] == offset


def aggregate(results: dict[str, dict]) -> dict:
    done = [r for r in results.values() if r.get("status") == "COMPLETED"]
    votes_a = sum(r.get("choice") == "A" for r in done)
    votes_b = sum(r.get("choice") == "B" for r in done)
    return {"winner": "A" if votes_a > votes_b else "B" if votes_b > votes_a else None,
            "votes_a": votes_a, "votes_b": votes_b,
            "live_votes": sum(bool(r.get("live")) for r in done)}


def public_panel(rows: list[dict]) -> dict:
    """Embargo every result until all three rows are terminal."""
    by_member = {r["member"]: r for r in rows}
    if any(m not in by_member or by_member[m]["status"] not in TERMINAL for m in PANEL):
        return {"status": "WAITING", "members": list(PANEL)}
    results = {}
    for m in PANEL:
        row = by_member[m]
        item = {k: row.get(k) for k in PUBLIC_FIELDS if k in row}
        item["live"] = bool(row.get("live"))
        results[m] = item
    return {"status": "REVEALED", "members": results, "order": list(PANEL), "aggregate": aggregate(results)}
