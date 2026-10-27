import json

import collector.source_probe as probe
from collector.auto_activate import auto_activate, name_for, role_for
from collector.discover_venues import annotate_area, area_of, discoveries_from_overpass, discoveries_from_wikidata
from pipeline.v2.convert import merge_duplicates


def _event(title, venue="Op Roakeldaishal", city="Warffum", date="2026-11-21", end="2026-11-22", time="13:00", url="https://a.example/"):
    return {"id": title, "title": title, "venue": {"name": venue, "city": city},
            "occurrences": [{"date": date, "endDate": end, "startTime": time, "endTime": None}],
            "sources": [{"url": url}], "tags": [], "url": url}


def test_zelfde_uitje_met_twee_namen_wordt_een():
    merged = merge_duplicates([_event("Winterfair Op Roakeldais"), _event("Winterfair Warffum", url="https://b.example/")])
    assert len(merged) == 1 and len(merged[0]["sources"]) == 2


def test_andere_tijd_of_andere_titel_blijft_apart():
    assert len(merge_duplicates([_event("Winterfair Warffum"), _event("Winterfair Warffum avond", time="19:00")])) == 2
    assert len(merge_duplicates([_event("Kerstconcert"), _event("Boekenmarkt")])) == 2
    assert len(merge_duplicates([_event("Najaarsmarkt", venue="Centrum Delfzijl"), _event("Najaarsmarkt kramen", venue="Centrum Delfzijl")])) == 2


def test_werkgebied_bepalen():
    assert area_of({"lat": 53.32, "lon": 6.86})[0] == "binnen"
    assert area_of({"lat": 53.37, "lon": 5.22})[0] == "binnen"  # Terschelling: Friesland hoort erbij
    assert area_of({"lat": 52.5168, "lon": 6.0830})[0] == "buiten"  # Zwolle
    assert area_of({"region": "Q752"}) == ("binnen", None)
    assert area_of({})[0] == "onbekend"


def test_coordinaten_uit_openstreetmap_en_wikidata():
    osm = discoveries_from_overpass({"elements": [{"type": "way", "id": 9, "center": {"lat": 53.2, "lon": 6.5},
                                                   "tags": {"amenity": "theatre", "website": "x.example"}}]})
    assert (osm[0]["lat"], osm[0]["lon"]) == (53.2, 6.5)
    wiki = discoveries_from_wikidata({"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q1"},
        "website": {"value": "https://f.example"}, "coord": {"value": "Point(5.22 53.37)"},
        "region": {"value": "http://www.wikidata.org/entity/Q770"}}]}})
    assert (wiki[0]["lat"], wiki[0]["lon"], wiki[0]["region"]) == (53.37, 5.22, "Q770")


def test_buiten_het_gebied_wordt_niet_getest(tmp_path):
    queue = tmp_path / "q.json"
    queue.write_text(json.dumps({"candidates": [
        {"host": "oerol.example", "url": "https://oerol.example/", "activationStatus": "candidate", "policyStatus": "review"},
        {"host": "dorpshuis.example", "url": "https://dorpshuis.example/", "activationStatus": "candidate", "policyStatus": "review"}]}))
    counts = annotate_area(str(queue), [{"url": "https://oerol.example/", "lat": 52.5168, "lon": 6.0830},  # Zwolle
                                        {"url": "https://dorpshuis.example/", "lat": 53.3, "lon": 6.8}])
    items = {c["host"]: c for c in json.loads(queue.read_text())["candidates"]}
    assert counts == {"binnen": 1, "onbekend": 0, "buiten": 1}
    assert items["oerol.example"]["policyStatus"] == "blocked"
    assert items["dorpshuis.example"]["policyStatus"] == "review"


def test_na_een_groter_werkgebied_komt_een_website_weer_aan_de_beurt(tmp_path):
    # Eerst (bij 60 km rond Groningen) buiten het gebied; Terschelling hoort nu bij het werkgebied.
    queue = tmp_path / "q.json"
    queue.write_text(json.dumps({"candidates": [
        {"host": "oerol.example", "url": "https://oerol.example/", "activationStatus": "candidate",
         "policyStatus": "blocked", "policyNote": "buiten het werkgebied (130 km van Groningen)", "areaStatus": "buiten",
         "evidence": [{"kind": "osm", "lat": 53.37, "lon": 5.22}]}]}))
    counts = annotate_area(str(queue), [])   # ook zonder nieuwe vondsten: de plek staat al in de wachtrij
    [item] = json.loads(queue.read_text())["candidates"]
    assert counts["binnen"] == 1 and item["areaStatus"] == "binnen"
    assert item["policyStatus"] == "review" and "policyNote" not in item


def test_goede_bron_gaat_automatisch_aan(tmp_path):
    good = {"id": "c1", "host": "podium.example", "url": "https://podium.example/", "activationStatus": "candidate",
            "policyStatus": "review", "probeStatus": "supported", "robotsStatus": "allowed", "extractor": "jsonld_event",
            "probeDetails": {}, "evidence": [{"kind": "osm", "anchorText": "Podium (theatre, Winsum)"}]}
    far = dict(good, id="c2", host="ver.example", url="https://ver.example/", areaStatus="buiten")
    queue, sources = tmp_path / "q.json", tmp_path / "s.json"
    queue.write_text(json.dumps({"candidates": [good, far]}))
    sources.write_text(json.dumps({"sources": []}))
    activated = auto_activate(str(queue), str(sources), "2026-10-11")
    assert [a["host"] for a in activated] == ["podium.example"]
    assert json.loads(sources.read_text())["sources"][0]["name"] == "Podium"
    assert name_for(good) == "Podium" and role_for(good) == "venue"


def test_robot_probeert_ook_programma_pagina(monkeypatch):
    class Event:
        title = "Voorstelling"
        start_date = "2099-01-01"  # alleen komende uitjes tellen
    class Page:
        status, content_type, text = 200, "text/html", "<html></html>"
    asked = []
    def fetcher(url, timeout):
        asked.append(url)
        return Page()
    monkeypatch.setattr(probe, "parse_agenda", lambda html, url: [Event(), Event()] if url.endswith("/programma/") else [])
    class Robots:
        def can_fetch(self, agent, url):
            return True
    found = probe._strict_agenda_probe("https://x.example/", Robots(), fetcher=fetcher, timeout=5)
    assert found["url"] == "https://x.example/programma/"
    assert asked[:4] == ["https://x.example/agenda/", "https://x.example/evenementen/", "https://x.example/activiteiten/", "https://x.example/programma/"]


def test_zelfde_uitje_op_twee_websites_met_een_andere_zaalnaam():
    # Drenthe/Friesland-ronde: workum.nl en het theater zelf ('Voorstelling Laurens de Groot – HUN').
    a = _event("Voorstelling Laurens de Groot – HUN", venue="Klameare")
    b = _event("Laurens de Groot – HUN", venue="Theater Klameare Workum")
    assert len(merge_duplicates([a, b])) == 1
    assert len(merge_duplicates([_event("Bieb Vibes: Bordspellencafé", venue="Bibliotheek"),
                                 _event("Bieb Vibes: Oplap & Cosplay atelier", venue="De Bieb")])) == 2
    # De dorpsagenda noemt alleen de plaats, zonder tijd; het theater heeft de zaal en de tijd.
    dorp = _event("Voorstelling The Diamond Baritones", venue="Warffum", time=None)
    zaal = _event("The Diamond Baritones – Wonderland", venue="Kultuerhús Klameare")
    merged = merge_duplicates([dorp, zaal])
    assert len(merged) == 1 and merged[0]["occurrences"][0]["startTime"]
    assert merged[0]["venue"]["name"] == "Kultuerhús Klameare" and merged[0]["title"] == "The Diamond Baritones – Wonderland"
