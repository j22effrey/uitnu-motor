"""Het werkgebied: Noord-Nederland (Groningen, Fryslân en Drenthe) plus een rand van 10 km."""
from pipeline import area
from pipeline.v2.gate import run_gate


def test_plaatsen_in_en_buiten_noord_nederland():
    binnen = {"Groningen": (53.2194, 6.5665), "Zuidlaren": (53.0938, 6.6830), "Leeuwarden": (53.2012, 5.7999),
              "Harlingen": (53.1746, 5.4214), "Vlieland": (53.2961, 5.0661), "Schiermonnikoog": (53.48, 6.16),
              "Emmen": (52.7858, 6.8975), "Coevorden": (52.6609, 6.7408), "Meppel": (52.6957, 6.1944),
              # vlak over de grens (rand van 10 km)
              "Steenwijk": (52.7871, 6.1196), "Emden": (53.3669, 7.2061)}
    buiten = {"Zwolle": (52.5168, 6.0830), "Lelystad": (52.5185, 5.4714), "Texel": (53.0549, 4.7977),
              "Papenburg": (53.0773, 7.4039), "Utrecht": (52.0907, 5.1214)}
    assert [name for name, (lat, lon) in binnen.items() if not area.in_area(lat, lon)] == []
    assert [name for name, (lat, lon) in buiten.items() if area.in_area(lat, lon)] == []
    assert area.in_area(None, None)   # zonder plek niet weggooien


def test_werkgebied_is_een_lijstje_provincies():
    assert area.iso_codes() == ["NL-GR", "NL-FR", "NL-DR"]
    assert area.wikidata_ids() == ["Q752", "Q770", "Q772"]
    # Een ander werkgebied (landelijk later): alleen het lijstje anders.
    assert area.in_area(52.0907, 5.1214, provinces=("Utrecht",))
    assert not area.in_area(53.2194, 6.5665, provinces=("Utrecht",), margin_km=0)
    assert area.describe()["provincies"] == ["Groningen", "Fryslân", "Drenthe"]


def test_bron_buiten_het_werkgebied_is_niet_ineens_leeg():
    def event(host, n):
        return [{"id": f"{host}{i}", "kind": "muziek", "url": "u", "occurrences": [{"date": "2026-11-01"}],
                 "venue": {"city": "x"}, "sources": [{"host": host}]} for i in range(n)]
    previous = event("podium.example", 12) + event("buitenland.example", 12)
    # De fabriek geeft alleen de vorige uitjes in het werkgebied door (zie build.py); dan keurt de
    # keuring goed, ook al levert de bron buiten het gebied niets meer.
    assert run_gate(event("podium.example", 12), previous[:12], "2026-10-13")["passed"]
    assert not run_gate(event("podium.example", 12), previous, "2026-10-13")["passed"]
