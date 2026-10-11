from datetime import date

from pipeline.v2.convert import merge_duplicates, parse_time_range, slugify, to_v2
from pipeline.v2.gate import run_gate

TODAY = date(2026, 10, 11)


def raw(**kw):
    base = {"id": "x1", "title": "Herfstmarkt", "startDate": "2026-10-17", "endDate": None,
            "time": "10:00 – 16:00", "location": "Centrum", "city": "Appingedam", "lat": 53.32,
            "lon": 6.86, "price": "Gratis", "sourceType": "organizer",
            "verificationStatus": "organizer_confirmed", "sourceUrl": "https://org.example/markt",
            "publicAudience": True}
    base.update(kw)
    return base


def test_tijden_uitlezen():
    assert parse_time_range("17:00 – 00:00") == ("17:00", "00:00")
    assert parse_time_range("vanaf 9.30 uur") == ("09:30", None)
    assert parse_time_range("Zie organisator") == (None, None)


def test_slug():
    assert slugify("Café & Kermis!") == "cafe-kermis"


def test_alleen_bevestigd_en_toekomst_wordt_publiek():
    assert to_v2(raw(), TODAY)
    assert to_v2(raw(verificationStatus="permit_applied"), TODAY) is None
    assert to_v2(raw(verificationStatus="municipal_calendar"), TODAY) is None
    assert to_v2(raw(publicAudience=False), TODAY) is None
    assert to_v2(raw(startDate="2026-10-01"), TODAY) is None
    assert to_v2(raw(startDate="2026-10-09", endDate="2026-10-12"), TODAY), "loopt nog"


def test_dubbele_records_worden_een_met_alle_bronnen():
    a = to_v2(raw(), TODAY)
    b = to_v2(raw(id="x2", sourceUrl="https://gemeente.example/vergunning"), TODAY)
    merged = merge_duplicates([a, b])
    assert len(merged) == 1
    assert len(merged[0]["sources"]) == 2


def _events(n, host="org.example", kind="markt"):
    return [{"id": f"e{i}", "kind": kind, "url": "https://x", "venue": {"city": "X"},
             "occurrences": [{"date": "2026-10-17"}], "sources": [{"host": host}]} for i in range(n)]


def test_keuring_keurt_goed():
    assert run_gate(_events(50), _events(50))["passed"]


def test_keuring_stopt_bij_flinke_daling():
    assert not run_gate(_events(30), _events(50))["passed"]


def test_keuring_stopt_als_grote_bron_leeg_is():
    previous = _events(40) + _events(15, host="podium.example")
    assert not run_gate(_events(48), previous)["passed"]


def test_keuring_stopt_bij_te_veel_overig():
    assert not run_gate(_events(40) + _events(10, kind="overig"), None)["passed"]


def test_voorbije_evenementen_tellen_niet_mee():
    previous = _events(30) + [dict(e, id=f"oud{i}", occurrences=[{"date": "2026-10-01"}]) for i, e in enumerate(_events(20))]
    assert run_gate(_events(30), previous, "2026-10-11")["passed"]
    assert not run_gate(_events(30), previous)["passed"], "zonder datum telt alles mee"
