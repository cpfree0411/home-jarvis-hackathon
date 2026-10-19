#!/usr/bin/env python3
"""Opt-in real Nebius check: one public fixture, no prompt/body logging, $0.25 ledger.

Requires NEBIUS_API_KEY in the process environment. No retries or alternate models.
The same budgeted writer is used by ui_smoke.py --live.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from otaku_gallery.evidence import Fixtures, gather_evidence  # noqa: E402
from otaku_gallery.errors import ResearchError  # noqa: E402
from otaku_gallery.nebius import HOST, MAX_TOKENS, MODEL, NebiusWriter  # noqa: E402
from otaku_gallery.research import build_page  # noqa: E402

INPUT_USD_PER_MILLION = 1.0
OUTPUT_USD_PER_MILLION = 3.0
PRICE_SOURCE = "https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/nemotron3-ultra-550b-a55b.md"
MAX_SPEND_USD = 0.25


class BudgetedWriter(NebiusWriter):
    def __init__(self, ledger, **kwargs):
        super().__init__(**kwargs)
        self.ledger = Path(ledger)
        self.calls = 0

    def write(self, query, records, **kwargs):
        self.api_key()  # no reservation for a missing credential
        if self.calls:
            raise ResearchError("smoke_one_call_only")
        payload = self.build_payload(query, records)
        if len(payload) > 24000:
            raise ResearchError("nebius_input_limit")
        # UTF-8 bytes conservatively bound text tokens; allow extra chat overhead.
        reserve = round(((len(payload) + 1024) * INPUT_USD_PER_MILLION
                         + MAX_TOKENS * OUTPUT_USD_PER_MILLION) / 1_000_000, 6)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        # Cross-process lock and fsync ensure a crash does not erase a reservation.
        import fcntl
        import os
        with self.ledger.open("a+", encoding="utf-8") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            file.seek(0)
            raw = file.read()
            data = json.loads(raw) if raw else {"limit_usd": MAX_SPEND_USD, "reservations": []}
            spent = sum(item["reserved_usd"] for item in data["reservations"])
            if spent + reserve > MAX_SPEND_USD:
                raise ResearchError("smoke_budget_exhausted")
            data["reservations"].append({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                         "reserved_usd": reserve, "model": MODEL})
            file.seek(0)
            file.truncate()
            json.dump(data, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        self.calls += 1
        return super().write(query, records, **kwargs)


def proof(writer):
    usage = dict(writer.usage)
    cost = (usage.get("prompt_tokens", 0) * INPUT_USD_PER_MILLION
            + usage.get("completion_tokens", 0) * OUTPUT_USD_PER_MILLION) / 1_000_000
    return {"provider": "Nebius Token Factory", "endpoint_host": HOST, "model": MODEL,
            "usage": usage, "metrics": dict(writer.metrics), "paid_calls": writer.calls,
            "estimated_cost_usd": round(cost, 6), "price_source": PRICE_SOURCE,
            "price_usd_per_million": {"input": INPUT_USD_PER_MILLION, "output": OUTPUT_USD_PER_MILLION},
            "response_model_validated": bool(usage), "strict_schema_validated": bool(usage)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=ROOT / "docs/validation/model-budget.json")
    parser.add_argument("--summary", type=Path, default=ROOT / "docs/validation/model-proof.json")
    args = parser.parse_args()
    writer = BudgetedWriter(args.ledger)
    fixtures = Fixtures(ROOT / "data/fixtures/wikipedia-snapshots.json")
    records, notes = gather_evidence("Cyberpunk", mode="fixture", fixtures=fixtures)
    result = {}
    ok = False
    try:
        output, _ = writer.write("Cyberpunk", records, timeout=45)
        page = build_page("Cyberpunk", output, records, notes)
        ok = page["status"] == "answered" and any(s["cited"] for s in page["sources"])
        result.update(status=page["status"], source_count=len(page["sources"]),
                      unverified_count=page["unverified_count"])
    except ResearchError as error:
        result["error_code"] = error.code
    result.update(proof(writer), passed=ok)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
