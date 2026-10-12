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
# De echte correcties en het festivalregister horen bij de indeling, zoals in de fabriek.
OVERRIDES = json.loads((Path(__file__).parents[2] / "pipeline" / "v2" / "overrides.json").read_text(encoding="utf-8"))


def _event(case: dict) -> dict:
    occ = {"date": "2026-10-17", "endDate": "2026-10-19" if case.get("multiday") else None}
    return {"id": case["title"], "title": case["title"], "description": case.get("description", ""),
            "price": case.get("price"), "occurrences": [occ], "sources": []}


def test_testset_scoort_minstens_95_procent():
    goed = sum(1 for c in CASES if classify(_event(c), OVERRIDES)["kind"] == c["kind"])
    assert goed / len(CASES) >= 0.95, f"{goed} van {len(CASES)} goed"


@pytest.mark.parametrize("case", CASES, ids=[c["title"] for c in CASES])
def test_soort_en_labels(case):
    verdict = classify(_event(case), OVERRIDES)
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


def test_festival_alleen_met_bewijs():
    """Vaste regel 3: 'festival' in de naam is geen bewijs; meerdere podia of het register wel."""
    def kind(title, description="", **extra):
        return classify({"id": title, "title": title, "description": description,
                         "occurrences": [{"date": "2026-10-17", "endDate": "2026-10-19"}], "sources": [], **extra})["kind"]
    assert kind("Springkussen Festival") == "kinderen"
    assert kind("Dorpsfestival") == "overig"
    assert kind("Dorpsfestival", "drie podia en een line-up met twintig bands") == "festival"
    assert kind("Dorpsfestival", pageHints={"podia": "line-up"}) == "festival"
    assert kind("Bevrijdingsfestival Groningen") != "festival"  # zonder register...
    assert classify(_event({"title": "Bevrijdingsfestival Groningen"}), OVERRIDES)["kind"] == "festival"  # ...met register wel


def test_organisator_zegt_wat_het_is():
    base = {"id": "x", "title": "Wende", "occurrences": [{"date": "2026-10-17"}], "sources": []}
    assert classify({**base, "schemaType": "TheaterEvent"})["kind"] == "theater"
    assert classify({**base, "schemaType": "Festival"})["kind"] == "overig"  # eigen opgave 'festival' telt niet
    assert classify({**base, "pageHints": {"soort": "muziek", "woord": "concert"}})["kind"] == "muziek"
    assert classify({**base, "title": "Kerstmarkt", "schemaType": "MusicEvent"})["kind"] == "markt"  # titel gaat voor


def test_correctie_heeft_altijd_een_reden():
    for entry in OVERRIDES["namen"]:
        assert entry["reden"] and entry["soort"] in KINDS, entry
