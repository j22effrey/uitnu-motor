"""De indeling wordt getoetst tegen een vaste testset met de juiste antwoorden.

Regel uit het bouwplan: een wijziging gaat pas door als minstens 95% klopt.
Breid testset_soorten.json uit tot zo'n 150 echte evenementen.
"""
import json
from pathlib import Path

import pytest

from pipeline.v2.classify import classify
from pipeline.v2.kinds import KINDS

CASES = json.loads((Path(__file__).parent / "testset_soorten.json").read_text(encoding="utf-8"))


def _event(case: dict) -> dict:
    occ = {"date": "2026-10-17", "endDate": "2026-10-19" if case.get("multiday") else None}
    return {"id": case["title"], "title": case["title"], "description": case.get("description", ""),
            "price": case.get("price"), "occurrences": [occ], "sources": []}


def test_testset_scoort_minstens_95_procent():
    goed = sum(1 for c in CASES if classify(_event(c))["kind"] == c["kind"])
    assert goed / len(CASES) >= 0.95, f"{goed} van {len(CASES)} goed"


@pytest.mark.parametrize("case", CASES, ids=[c["title"] for c in CASES])
def test_soort_en_labels(case):
    verdict = classify(_event(case))
    assert verdict["kind"] == case["kind"], verdict["reason"]
    for tag in case.get("tags", []):
        assert tag in verdict["tags"]
    for tag in case.get("not_tags", []):
        assert tag not in verdict["tags"]


def test_elke_uitkomst_heeft_uitleg():
    verdict = classify(_event({"title": "Iets onduidelijks"}))
    assert verdict["kind"] in KINDS
    assert verdict["method"] and verdict["reason"] and 0 <= verdict["confidence"] <= 1


def test_correctie_wint_altijd():
    event = _event({"title": "Stadswandeling met gids"})
    assert classify(event, {event["id"]: "kunst"})["kind"] == "kunst"
