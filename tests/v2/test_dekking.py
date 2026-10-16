"""De dekkingslijst: valt een podium dat erin hoort op als het ontbreekt of te weinig oplevert?"""
import json
from datetime import date
from pathlib import Path

from pipeline.v2.dekking import coverage, load_register

TODAY = date(2026, 10, 16)


def ev(i, host, day, end=None):
    return {"id": f"e{i}", "sources": [{"host": host}], "occurrences": [{"date": day, "endDate": end}]}


REGISTER = {"plaatsen": {"Groningen": [
    {"naam": "Vera", "website": "https://www.vera-groningen.nl/", "hosts": ["vera-groningen.nl"], "verwacht90": 3},
    {"naam": "SPOT", "website": "https://www.spotgroningen.nl/", "hosts": ["spotgroningen.nl"], "verwacht90": 2},
    {"naam": "Tumult", "website": "https://tumultgroningen.nl/", "hosts": ["tumultgroningen.nl", "bijvrijdag.nl"], "verwacht90": 1},
    {"naam": "ESNS", "website": "https://esns.nl/", "hosts": ["esns.nl"], "jaarlijks": True},
]}}


def test_ontbreekt_te_weinig_en_goed():
    events = [ev(1, "spotgroningen.nl", "2026-10-20"), ev(2, "www.spotgroningen.nl", "2026-11-01"),
              ev(3, "vera-groningen.nl", "2026-10-30"),
              ev(4, "vera-groningen.nl", "2027-03-01"),          # buiten de 90 dagen
              ev(5, "bijvrijdag.nl", "2026-10-01", "2026-10-31"),  # loopt nog: telt mee (oude naam)
              ev(6, "esns.nl", "2027-01-14")]                      # jaarlijks: de volgende editie staat erin
    result = coverage(events, REGISTER, TODAY)
    assert result["gecontroleerd"] == 4
    assert result["goed"] == 3
    assert [r["naam"] for r in result["teWeinig"]] == ["Vera"]
    assert result["teWeinig"][0]["gevonden"] == 1 and result["teWeinig"][0]["verwacht"] == 3
    assert result["ontbreekt"] == []


def test_voorbij_telt_niet_en_jaarlijks_zonder_editie_ontbreekt():
    result = coverage([ev(1, "esns.nl", "2026-01-15")], REGISTER, TODAY)
    assert {r["naam"] for r in result["ontbreekt"]} == {"Vera", "SPOT", "Tumult", "ESNS"}


def test_echte_lijst_is_leesbaar():
    register = load_register(Path("collector/dekking.json"))
    places = register["plaatsen"]["Groningen"]
    assert len(places) >= 60
    for place in places:
        assert place["hosts"] and place["website"].startswith("http")
        assert place.get("jaarlijks") or place.get("verwacht90", 0) >= 1
    names = {p["naam"].split(" (")[0] for p in places}
    assert {"Vera", "Simplon", "Grand Theatre", "Paradigm", "Groninger Museum"} <= names
    assert load_register(Path("bestaat-niet.json")) == {}
