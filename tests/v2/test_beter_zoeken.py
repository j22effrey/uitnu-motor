"""Beter zoeken: meer agenda's kunnen lezen, en meer websites vinden en testen."""
from datetime import date

from collector.dutch_agenda_html import parse_agenda, parse_dutch_date

TODAY = date(2026, 10, 12)


def _events(html):
    return [(e.title, e.start_date, e.time_text) for e in parse_agenda(html, "https://dorp.example/agenda/", today=TODAY)]


# ---------------------------------------------------------------- datums

def test_datums_in_allerlei_vormen():
    assert parse_dutch_date("17 oktober 2026") == date(2026, 10, 17)
    assert parse_dutch_date("17-10-2026") == date(2026, 10, 17)
    assert parse_dutch_date("17/10/2026, 20:00 uur") == date(2026, 10, 17)
    assert parse_dutch_date("2026-11-13T19:00:00+01:00") == date(2026, 11, 13)
    # Zonder jaar alleen als de weekdag klopt: vrijdag 13 november bestaat in 2026.
    assert parse_dutch_date("vrijdag 13 november", TODAY) == date(2026, 11, 13)
    assert parse_dutch_date("za 9 jan", TODAY) == date(2027, 1, 9)
    assert parse_dutch_date("maandag 13 november", TODAY) is None   # klopt in geen enkel jaar dichtbij
    assert parse_dutch_date("13 november", TODAY) is None           # zonder weekdag: te onzeker
    assert parse_dutch_date("Tel. 050-1234567") is None
    assert parse_dutch_date("31-02-2026") is None


# ---------------------------------------------------------------- agenda's met kaartjes

def test_datum_voor_de_titel_in_hetzelfde_kaartje():
    html = """<main><h1>Agenda</h1>
      <article class="event"><div class="date"><span>vr</span> <span>13 nov 2026</span></div>
        <h3><a href="/spookbosch">Spookbosch</a></h3><p>19:00 - 22:00</p></article>
      <article class="event"><div class="date">za 14 nov 2026</div>
        <h3><a href="/kienen">Kienen in het dorpshuis</a></h3><p>aanvang 20:00</p></article>
    </main>"""
    assert _events(html) == [("Spookbosch", "2026-11-13", "19:00 – 22:00"),
                             ("Kienen in het dorpshuis", "2026-11-14", "20:00")]


def test_nooit_de_datum_van_het_volgende_kaartje_lenen():
    html = """<ul>
      <li><h3>Zonder datum</h3><p>Binnenkort meer</p></li>
      <li><time datetime="2026-11-20">20 nov</time><h3>Pubquiz</h3></li>
    </ul>"""
    assert _events(html) == [("Pubquiz", "2026-11-20", None)]


def test_time_element_en_regelafbreking():
    html = """<div class="agenda-item"><h2>Open dag Molen De Hoop</h2>
      <p><time datetime="2026-11-07T10:00">7 november</time><br>10:00 - 16:00</p></div>
      <div class="agenda-item"><h2>Snertwandeling</h2><p>Datum: 05-12-2026<br>start om 13.30</p></div>"""
    assert _events(html) == [("Open dag Molen De Hoop", "2026-11-07", "10:00 – 16:00"),
                             ("Snertwandeling", "2026-12-05", "13:30")]


def test_uitjes_onder_een_datumkopje():
    html = """<h2>Zaterdag 17 oktober</h2>
      <h3>Rommelmarkt</h3><p>09:00 - 14:00</p>
      <h3>Dansavond</h3><p>vanaf 21:00</p>
      <h2>Zondag 18 oktober</h2>
      <h3>Kerkconcert</h3><p>aanvang 15:00</p>
      <h2>Contact</h2><h3>Bestuur</h3>"""
    assert _events(html) == [("Rommelmarkt", "2026-10-17", "09:00 – 14:00"),
                             ("Dansavond", "2026-10-17", "21:00"),
                             ("Kerkconcert", "2026-10-18", "15:00")]


def test_platte_pagina_blijft_streng():
    html = """<div class="content"><h2>Toneelavond</h2><p>14 november 2026</p>
      <h2>Nieuwe leden welkom</h2><p>Kom eens kijken.</p></div>"""
    assert _events(html) == [("Toneelavond", "2026-11-14", None)]


# ---------------------------------------------------------------- de test van websites

import json

import collector.source_probe as probe
from collector.site_crawler import Fetched


def _cand(host, status=None, **extra):
    item = {"host": host, "url": f"https://{host}/", "activationStatus": "candidate", "policyStatus": "review"}
    if status:
        item["probeStatus"] = status
    item.update(extra)
    return item


def test_elke_ronde_vooral_nieuwe_websites(tmp_path):
    queue = tmp_path / "q.json"
    queue.write_text(json.dumps({"candidates": [
        _cand("al-getest.example", "no_supported_extractor", probedAt="2026-10-11", probeVersion=probe.PROBE_VERSION),
        _cand("oude-test.example", "no_supported_extractor"),            # oudere versie van de test
        _cand("lang-geleden.example", "no_supported_extractor", probedAt="2026-09-01", probeVersion=probe.PROBE_VERSION),
        _cand("nieuw.example"),
        _cand("tip.example", evidence=[{"kind": "tip"}]),
        _cand("ver.example", areaStatus="buiten"),
        _cand("klaar.example", "supported"),
    ]}))
    tested = []

    def fake_probe(url, **kw):
        tested.append(url)
        return probe.ProbeResult(url, url.split("/")[2], "allowed", "no_supported_extractor", [], None, {})

    original = probe.probe_source
    probe.probe_source = fake_probe
    try:
        probe.probe_queue(queue, limit=3, workers=1, today="2026-10-12")
    finally:
        probe.probe_source = original
    # Eerst de tip, dan wat een oudere versie van de test afwees, dan wat nog nooit getest is.
    assert [u.split("/")[2] for u in tested] == ["tip.example", "oude-test.example", "nieuw.example"]
    saved = {c["host"]: c for c in json.loads(queue.read_text())["candidates"]}
    assert saved["nieuw.example"]["probedAt"] == "2026-10-12" and saved["nieuw.example"]["probeVersion"] == probe.PROBE_VERSION
    day = probe.date(2026, 10, 12)
    assert probe.probe_due(saved["lang-geleden.example"], day)          # na drie weken weer aan de beurt
    assert not probe.probe_due(saved["al-getest.example"], day)
    assert not probe.probe_due(saved["ver.example"], day)


def test_agenda_via_de_link_op_de_voorpagina():
    home = """<html><nav><a href="/">Home</a><a href="/wat-is-er-te-doen">Wat is er te doen?</a>
      <a href="https://facebook.com/dorp">Facebook</a><a href="/nieuws">Nieuws</a></nav></html>"""
    agenda = """<html><article><h3>Spookbosch</h3><p>vrijdag 13 november 2026</p></article>
      <article><h3>Kerstmarkt</h3><p>zaterdag 12 december 2026</p></article></html>"""
    pages = {"https://dorp.example/": home, "https://dorp.example/wat-is-er-te-doen": agenda}

    def fetcher(url, timeout=15):
        if url.endswith("/robots.txt"):
            return Fetched(url, 404, "text/plain", "")
        return Fetched(url, 200 if url in pages else 404, "text/html", pages.get(url, ""))

    result = probe.probe_source("https://dorp.example/", fetcher=fetcher, today=TODAY)
    assert result.probe_status == "supported" and result.suggested_extractor == "html_agenda_dutch"
    assert result.details["html_agenda"]["url"] == "https://dorp.example/wat-is-er-te-doen"
    assert probe.agenda_links(home, "https://dorp.example/") == ["https://dorp.example/wat-is-er-te-doen"]


def test_geen_robots_txt_betekent_welkom_een_storing_betekent_later_opnieuw():
    from urllib.error import HTTPError

    def missing(url, timeout=15):
        if url.endswith("/robots.txt"):
            raise HTTPError(url, 404, "Not Found", {}, None)
        return Fetched(url, 200, "text/html", "<html></html>")

    def down(url, timeout=15):
        raise TimeoutError("geen antwoord")

    def forbidden(url, timeout=15):
        if url.endswith("/robots.txt"):
            return Fetched(url, 200, "text/plain", "User-agent: *\nDisallow: /")
        return Fetched(url, 200, "text/html", "<html></html>")

    assert probe.probe_source("https://zonder.example/", fetcher=missing).robots_status == "allowed"
    stormy = probe.probe_source("https://storing.example/", fetcher=down)
    assert (stormy.robots_status, stormy.probe_status) == ("unavailable", "error")
    assert probe.probe_source("https://nee.example/", fetcher=forbidden).probe_status == "blocked"
    # Eerder onterecht 'geblokkeerd' door een storing of ontbrekende robots.txt: opnieuw testen.
    old = {"activationStatus": "candidate", "probeStatus": "blocked", "probeDetails": {"robots": "unavailable"}}
    assert probe.probe_due(old, probe.date(2026, 10, 12))


# ---------------------------------------------------------------- meer websites vinden

from collector import discover_venues as dv


def test_dorpen_gemeenten_verenigingen_en_cafes_uit_openstreetmap():
    query = dv.overpass_query(60)
    for tag in ('"place"="village"', '"place"="hamlet"', '"amenity"="townhall"', '"office"="association"', '"amenity"="pub"'):
        assert tag in query
    found = dv.discoveries_from_overpass({"elements": [
        {"type": "node", "id": 7, "lat": 53.19, "lon": 6.77, "tags": {"place": "village", "name": "Froombosch", "website": "www.froombosch.com"}},
        {"type": "node", "id": 8, "tags": {"amenity": "townhall", "name": "Gemeentehuis", "website": "https://www.midden-groningen.nl"}},
    ]})
    assert [(f["url"], f["anchor_text"]) for f in found] == [
        ("https://www.froombosch.com/", "Froombosch (village, Froombosch)"),   # het dorp is zelf de plaats
        ("https://www.midden-groningen.nl/", "Gemeentehuis (townhall)")]


def test_dorpen_en_gemeenten_uit_wikidata():
    payload = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "Froombosch"},
         "website": {"value": "https://www.froombosch.com"}, "coord": {"value": "Point(6.77 53.19)"},
         "type": {"value": "http://www.wikidata.org/entity/Q532"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q2"}, "itemLabel": {"value": "Midden-Groningen"},
         "website": {"value": "https://www.midden-groningen.nl"}, "type": {"value": "http://www.wikidata.org/entity/Q2039348"}},
    ]}}
    found = dv.discoveries_from_wikidata_places(payload)
    assert [f["anchor_text"] for f in found] == ["Froombosch (dorp)", "Midden-Groningen (gemeente)"]
    assert found[0]["lat"] == 53.19 and found[0]["lon"] == 6.77
    assert "wikibase:around" in dv.WIKIDATA_PLACES_QUERY and "P856" in dv.WIKIDATA_PLACES_QUERY


def test_tip_van_de_eigenaar_komt_elke_ronde_in_de_wachtrij(tmp_path):
    tips, queue, known = tmp_path / "tips.json", tmp_path / "q.json", tmp_path / "known.json"
    tips.write_text(json.dumps({"tips": [{"url": "www.froombosch.com", "naam": "Froombosch", "reden": "Spookbosch ontbrak"},
                                         {"url": "https://www.facebook.com/groups/froombosch"}]}))
    known.write_text(json.dumps({"sources": []}))
    assert dv.main(["--queue", str(queue), "--known", str(known), "--tips", str(tips),
                    "--village-sites", str(tmp_path / "geen.json"), "--tips-only"]) == 0
    [item] = json.loads(queue.read_text())["candidates"]
    assert item["host"] == "froombosch.com" and item["areaStatus"] == "binnen"   # Facebook nooit
    assert item["evidence"][0]["kind"] == "tip" and item["evidence"][0]["anchorText"] == "Froombosch (tip)"
    # Een tip wordt (opnieuw) getest, ook als de site kort geleden nog 'niet leesbaar' was.
    item.update(probeStatus="no_supported_extractor", probedAt="2000-01-01", probeVersion=probe.PROBE_VERSION)
    assert probe.probe_due(item, probe.date(2026, 10, 12))
    item["probedAt"] = "2999-01-01"
    assert not probe.probe_due(item, probe.date(2026, 10, 12))


def test_kaartpin_bij_handmatig_uitje_met_alleen_een_plaatsnaam(tmp_path):
    from collector.geocode_curated import fill_coordinates
    from collector.pdok_geocode import GeoResult
    path = tmp_path / "events.json"
    path.write_text(json.dumps([
        {"id": "a", "title": "Spookbosch", "city": "Froombosch", "lat": None, "lon": None},
        {"id": "b", "title": "Markt", "city": "Haren", "lat": 53.17, "lon": 6.6},
        {"id": "c", "title": "Iets", "city": "Nergenshuizen"},
    ], indent=2))
    asked = []

    def geocode(name, rows=6, timeout=8):
        asked.append(name)
        if name == "Froombosch":
            return [GeoResult("Froombosch Kerk, Froombosch", 53.1, 6.7, "adres"),
                    GeoResult("Froombosch, Midden-Groningen, Groningen", 53.19123456, 6.77123456, "woonplaats")]
        return []

    assert fill_coordinates(path, geocode) == ["Froombosch"]
    rows = json.loads(path.read_text())
    assert (rows[0]["lat"], rows[0]["lon"]) == (53.19123, 6.77123)   # de woonplaats, niet een adres
    assert asked == ["Froombosch", "Nergenshuizen"]                      # Haren had al een kaartpin
    assert not path.read_text().endswith("\n")                           # opmaak van het bestand blijft gelijk


def test_spookbosch_staat_in_de_handmatige_agenda():
    rows = json.loads(open("data/events.json", encoding="utf-8").read())
    [row] = [r for r in rows if r["id"] == "spookbosch-froombosch-2026"]
    assert (row["startDate"], row["city"]) == ("2026-11-13", "Froombosch")
    assert row["eventUrl"] == "https://www.froombosch.com/wp/evenementen/"


def test_kaartje_met_ondertitel_en_pagina_over_een_uitje():
    # Een tweede kopje in het kaartje (ondertitel) mag de datum niet onvindbaar maken.
    html = """<section><article><h3>Toneel: De Vrek</h3><h4>Toneelvereniging Ons Genoegen</h4>
      <p>zaterdag 21 november 2026, aanvang 20:00</p></article>
      <article><h3>Klaverjassen</h3><h4>Biljartvereniging</h4><p>28-11-2026</p></article></section>"""
    found = _events(html)
    assert ("Toneel: De Vrek", "2026-11-21", "20:00") in found
    assert ("Klaverjassen", "2026-11-28", None) in found
    assert all(e[1] != "2026-11-28" for e in found if e[0].startswith("Toneel"))
    # Pagina over één uitje: geen datum uit de kop van de website lenen.
    single = """<html><header><p>Vandaag: maandag 12 oktober 2026</p></header>
      <main><h1>Lezing over de Ploeg</h1><p>Meer informatie volgt.</p></main></html>"""
    assert _events(single) == []


def test_groepskopje_is_geen_uitje_en_geen_titel():
    html = """<section><h2>Concerten</h2><h3>Wende</h3><p>vrijdag 29 januari 2027</p></section>
      <section><h2>Theater</h2><h3>Jochem Myjer</h3><p>12-02-2027</p></section>"""
    assert _events(html) == [("Wende", "2027-01-29", None), ("Jochem Myjer", "2027-02-12", None)]


def test_nieuwspagina_is_geen_agenda_en_landelijke_overheid_geen_bron(tmp_path):
    news = """<html><article><h3>Defensiejournaal 8 oktober 2026</h3><p>8 oktober 2026</p></article>
      <article><h3>Stagedag biedt diepgang</h3><p>1 oktober 2026</p></article>
      <article><h3>Datum en tijd</h3><p>15-10-2026, 10:00 - 17:00</p></article></html>"""

    def fetcher(url, timeout=15):
        if url.endswith("/robots.txt"):
            return Fetched(url, 404, "text/plain", "")
        return Fetched(url, 200, "text/html", news if url.endswith("/activiteiten/") else "<html></html>")

    # Alleen datums in het verleden, en 'Datum en tijd' is een label: geen agenda.
    assert probe.probe_source("https://nieuws.example/", fetcher=fetcher, today=TODAY).probe_status == "no_supported_extractor"
    assert "Datum en tijd" not in [e[0] for e in _events(news)]

    from collector.auto_activate import deep_page, eligible
    assert dv.is_excluded("https://www.defensie.nl/activiteiten/")
    deep = {"activationStatus": "candidate", "probeStatus": "supported", "robotsStatus": "allowed", "policyStatus": "review",
            "url": "https://www.groot.example/organisatie/vliegbases/leeuwarden/omgeving"}
    assert deep_page(deep["url"]) and not eligible(deep)
    assert eligible(dict(deep, url="https://www.dorpshuis.example/"))

    from collector.active_source_runner import load_active_sources
    registry = tmp_path / "sources.json"
    registry.write_text(json.dumps({"sources": [
        {"id": "a", "rootUrl": "https://www.defensie.nl/", "enabled": True},
        {"id": "b", "rootUrl": "https://www.dorpshuis.example/", "enabled": True}]}))
    assert [s["id"] for s in load_active_sources(registry)] == ["b"]


def test_fabriek_publiceert_nooit_uitjes_van_een_uitgesloten_website(tmp_path):
    from pipeline.v2.build import build
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    (data / "events.json").write_text(json.dumps([
        {"id": "x", "title": "Agenda IT-tafels", "startDate": "2026-10-15", "city": "Leeuwarden",
         "verificationStatus": "organizer_confirmed", "eventUrl": "https://www.defensie.nl/nieuws/x", "sourceUrl": "https://www.defensie.nl/nieuws/x"},
        {"id": "y", "title": "Kerstmarkt", "startDate": "2026-12-12", "city": "Haren",
         "verificationStatus": "organizer_confirmed", "eventUrl": "https://markt.example/", "sourceUrl": "https://markt.example/"},
    ]))
    events, status = build(data, out, TODAY, {}, photo_cache={})
    assert [e["title"] for e in events] == ["Kerstmarkt"] and status["uitgeslotenBron"] == 1


def test_mailadres_is_geen_link_van_een_uitje_en_start_is_geen_titel():
    html = """<div><h3>101 Dalmatiërs</h3><p>zaterdag 14 november 2026, 15:00</p>
      <p><a href="mailto:kaartverkoop@theater.example">Kaartverkoop</a></p></div>
      <div><h3>Gespreksgroep</h3><p>Start: 10 november 2026</p></div>
      <div><h3>Leerhuis</h3><p>Start: 17 november 2026</p></div>
      <div><h3>Meditatie</h3><p>Start: 24 november 2026</p></div>"""
    events = parse_agenda(html, "https://theater.example/agenda/", today=TODAY)
    assert not any((e.event_url or "").startswith("mailto:") for e in events)
    assert "Start" not in {e.title for e in events}
