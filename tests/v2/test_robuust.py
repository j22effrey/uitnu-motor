"""Eén kapotte bron mag de hele ronde niet laten vastlopen (ronde 7 van 13 oktober liep vast op een link
met tekst erin: 'https://...:00 uur. Nadere info volgt.')."""
from datetime import date

from collector.discover_venues import discoveries_from_wikidata_places, wikidata_label
from collector.source_candidates import canonical_url, host_key
from pipeline.v2.build import convert_all
from pipeline.v2.convert import to_v2

TODAY = date(2026, 10, 13)
BROKEN = "https://www.dorpshuis.example:00 uur. Nadere info volgt.  Alvast opgeven kan: <a href='"


def test_kapotte_link_is_geen_webadres():
    assert canonical_url(BROKEN) == "" and host_key(BROKEN) == ""
    assert canonical_url("https://www.dorpshuis example.nl/") == ""
    # Gewone webadressen blijven werken, ook met een eigen poort.
    assert canonical_url("https://www.Dorpshuis.example:443/agenda?x=1#kop") == "https://www.dorpshuis.example/agenda?x=1"
    assert canonical_url("http://dorpshuis.example:8080/") == "http://dorpshuis.example:8080/"


def _record(**extra):
    return {"title": "Bingo", "startDate": "2026-10-20", "city": "Eenrum",
            "verificationStatus": "organizer_confirmed", **extra}


def test_uitje_met_kapotte_link_krijgt_de_goede_link_of_valt_weg():
    good = "https://www.dorpshuis.example/agenda"
    event = to_v2(_record(eventUrl=BROKEN, sourceUrl=good), TODAY)
    assert event["url"] == good and [s["url"] for s in event["sources"]] == [good]
    assert to_v2(_record(eventUrl=BROKEN, sourceUrl=BROKEN), TODAY) is None


def test_een_kapot_uitje_houdt_de_rest_niet_tegen():
    good = _record(sourceUrl="https://www.dorpshuis.example/agenda")
    broken = _record(title="Kapot", sourceUrl="https://www.dorpshuis.example/x", startDate=20261020)  # geen tekst
    events, problems = convert_all([broken, good], TODAY)
    assert [e["title"] for e in events] == ["Bingo"]
    assert len(problems) == 1 and problems[0].startswith("Kapot")


def test_wikidata_code_is_geen_plaatsnaam():
    assert wikidata_label({"itemLabel": {"value": "Q1977146"}}) is None
    assert wikidata_label({"itemLabel": {"value": "Wehe-den Hoorn"}}) == "Wehe-den Hoorn"
    rows = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q1977146"}, "itemLabel": {"value": "Q1977146"},
         "website": {"value": "http://www.wehe-denhoorn.nl/"}, "coord": {"value": "Point(6.42 53.36)"},
         "type": {"value": "http://www.wikidata.org/entity/Q532"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "Eenrum"},
         "website": {"value": "https://eenrum.nl/"}, "coord": {"value": "Point(6.46 53.36)"},
         "type": {"value": "http://www.wikidata.org/entity/Q532"}},
    ]}}
    found = discoveries_from_wikidata_places(rows)
    assert [f["anchor_text"] for f in found] == [None, "Eenrum (dorp)"]
