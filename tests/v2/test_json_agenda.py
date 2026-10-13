"""Een agenda die de website zelf als gegevens (JSON) aanbiedt, zoals Atlas Theater in Emmen."""
import json

import pytest

from collector.active_source_runner import run_source
from collector.json_api_events import fetch, parse_items, value_at
from collector.site_crawler import Fetched
from pipeline.v2.classify import classify

ROOT = "https://www.theater.example/"
CONFIG = {
    "endpointUrl": "https://www.theater.example/api/voorstellingen",
    "items": "",
    "title": ["Performance.Artist", "Performance.Title"],
    "start": "Performance.StartTime",
    "url": "Url",
    "id": "Performance.PerformanceID",
    "genre": "Performance.Genre",
    "genres": {"Muziek": "MusicEvent", "Cabaret": "ComedyEvent"},
    "room": "Performance.Room",
    "rooms": {"De Grote Kerk": {"venue": "Grote Kerk", "city": "Emmen"}},
    "skipTitle": r"\bserie \d|abonnement",
}
DATA = [
    {"Url": "/voorstellingen/kordaat-20-okt/", "Performance": {"PerformanceID": 1, "Artist": "Kor Hoebe",
     "Title": "Kordaat", "StartTime": "2026-10-20T20:30:00+02:00", "Genre": "Cabaret", "Room": "Grote Zaal"}},
    {"Url": "/voorstellingen/dna-21-nov/", "Performance": {"PerformanceID": 2, "Artist": "DNA",
     "Title": "Dianto Reed Quintet", "StartTime": "2026-11-21T20:00:00+01:00", "Genre": "Muziek", "Room": "De Grote Kerk"}},
    {"Url": "/voorstellingen/aatje/", "Performance": {"PerformanceID": 3, "Artist": "Aatje viert Feest! | 4+",
     "Title": "", "StartTime": "2026-10-18T14:00:00+02:00", "Genre": "Jeugd en familie", "Room": "DVHN Zaal"}},
    {"Url": "/voorstellingen/serie/", "Performance": {"PerformanceID": 4, "Artist": "Cabaret Serie 1 - 2026/2027",
     "Title": "3 avonden lachen", "StartTime": "2026-10-23T20:30:00+02:00", "Genre": "Cabaret", "Room": "Grote Zaal"}},
    {"Url": "/voorstellingen/zonder-datum/", "Performance": {"PerformanceID": 5, "Artist": "Zonder datum"}},
]


def test_gegevens_op_een_plek():
    assert value_at({"a": {"b": [1, {"c": 2}]}}, "a.b.1.c") == 2
    assert value_at([1, 2], "") == [1, 2] and value_at({"a": 1}, "a.b") is None


def test_voorstellingen_uit_de_gegevens():
    events = parse_items(DATA, CONFIG, source_name="Theater", root_url=ROOT)
    assert [e.title for e in events] == ["Kor Hoebe – Kordaat", "DNA – Dianto Reed Quintet", "Aatje viert Feest! | 4+"]
    first, church, kids = events
    assert first.source_url == "https://www.theater.example/voorstellingen/kordaat-20-okt/"
    assert first.start_at == "2026-10-20T20:30:00+02:00" and first.source_id == "1"
    assert first.category == "ComedyEvent" and first.venue is None          # de vaste zaal komt van de bron
    assert (church.venue, church.city, church.category) == ("Grote Kerk", "Emmen", "MusicEvent")
    assert kids.category == "Jeugd en familie"                              # niet omgezet: blijft het genre


def test_robots_en_de_hele_bron():
    def robots(url, timeout=15):
        return Fetched(url, 200, "text/plain", "User-agent: *\nDisallow:")

    events = fetch(CONFIG, source_name="Theater", root_url=ROOT, robots_fetch=robots,
                   json_fetch=lambda url, timeout=15: json.dumps(DATA))
    assert len(events) == 3

    def forbidden(url, timeout=15):
        return Fetched(url, 200, "text/plain", "User-agent: *\nDisallow: /api/")

    with pytest.raises(PermissionError):
        fetch(CONFIG, source_name="Theater", root_url=ROOT, robots_fetch=forbidden, json_fetch=lambda u, timeout=15: "[]")

    source = {"id": "theater", "name": "Theater", "rootUrl": ROOT, "role": "venue", "extractorHint": "json_api",
              "extractorConfig": CONFIG, "defaultPlace": {"city": "Emmen", "venue": "Atlas Theater"}}
    result = run_source(source, json_fetch=lambda config, **kw: parse_items(DATA, config, source_name="Theater",
                                                                             root_url=ROOT))
    assert result.extractor == "json_api" and len(result.events) == 3
    assert result.events[0].verification_status == "organizer_confirmed"
    assert (result.events[0].venue, result.events[0].city) == ("Atlas Theater", "Emmen")   # vaste zaal van de bron
    assert (result.events[1].venue, result.events[1].city) == ("Grote Kerk", "Emmen")       # eigen plek blijft


def test_soort_van_de_organisator_gaat_voor_de_rubriek_in_de_link():
    # Alles staat onder /voorstellingen/ (rubriek 'theater'), maar een concert is muziek.
    event = {"title": "DNA – Dianto Reed Quintet", "url": "https://www.theater.example/voorstellingen/dna-21-nov/",
             "schemaType": "MusicEvent", "sources": []}
    assert classify(event)["kind"] == "muziek"
    event["schemaType"] = None
    assert classify(event)["kind"] == "theater"
