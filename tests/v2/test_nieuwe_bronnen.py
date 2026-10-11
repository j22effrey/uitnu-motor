"""Nieuwe bronnen moeten ook echt uitjes opleveren (en geen rommel)."""
import json

import collector.source_probe as probe
from collector.active_source_runner import apply_default_place, run_source
from collector.dutch_agenda_html import parse_agenda
from collector.site_crawler import CrawlSource, Fetched, crawl_source
from collector.source_activation import default_place_for
from collector.source_candidates import merge_candidates
from collector.title_place_inference import locate_city
from pipeline.event_model import RawEvent
from pipeline.publishability import decide

PROGRAMMA = """<html><body>
<h2>Fleddy Melculy</h2><p>vrijdag 14 november 2026</p><p>20:00 - 23:00</p>
<h2>Meld je aan en blijf op de hoogte van nieuwe shows</h2><p>1 januari 2026</p>
<h2>Wat is er te doen?</h2><p>2 november 2026</p>
</body></html>"""


def _site(pages):
    def fetcher(url, timeout=15):
        if url.endswith("/robots.txt"):
            return Fetched(url, 404, "text/plain", "")
        if url in pages:
            return Fetched(url, 200, "text/html", pages[url])
        return Fetched(url, 404, "text/html", "")
    return fetcher


def _raw(**fields):
    base = dict(source_name="Podium", source_type="structured_web", source_url="https://podium.example/x",
                source_id=None, title="Concert", start_at="2026-11-14T20:00:00",
                verification_status="organizer_confirmed")
    base.update(fields)
    return RawEvent(**base)


def test_programma_pagina_uit_de_probe_wordt_gelezen():
    source = CrawlSource.from_dict({
        "id": "podium-web", "name": "Podium", "rootUrl": "https://podium.example/", "role": "venue",
        "extractorHint": "html_agenda_dutch", "minDelaySeconds": 0,
        "extractorConfig": {"agendaUrl": "https://podium.example/programma/"},
    })
    result = crawl_source(source, fetcher=_site({"https://podium.example/programma/": PROGRAMMA}),
                          sleeper=lambda s: None)
    assert [e.title for e in result.events] == ["Fleddy Melculy"]
    assert result.events[0].start_at == "2026-11-14T20:00:00"


def test_kopjes_en_oproepen_zijn_geen_uitjes():
    titles = [e.title for e in parse_agenda(PROGRAMMA, "https://podium.example/programma/")]
    assert titles == ["Fleddy Melculy"]


def test_uitje_zonder_plaats_krijgt_de_plek_van_het_podium():
    place = {"venue": "Neushoorn", "city": "Leeuwarden"}
    filled = apply_default_place(_raw(), place)
    assert (filled.venue, filled.city, filled.raw["place_from_source"]) == ("Neushoorn", "Leeuwarden", True)
    assert decide(filled).action == "publish"
    assert decide(_raw()).action == "review"  # zonder plek blijft het liggen


def test_eigen_plaats_of_andere_zaal_wint_altijd():
    place = {"venue": "Neushoorn", "city": "Leeuwarden"}
    assert apply_default_place(_raw(city="Groningen"), place).city == "Groningen"
    assert apply_default_place(_raw(venue="Galerie Mildam"), place).city is None


def test_vaste_plek_geldt_voor_alle_extractors():
    source = {"id": "p", "name": "Podium", "rootUrl": "https://podium.example/", "role": "venue",
              "extractorHint": "wordpress_tribe", "defaultPlace": {"venue": "Podium", "city": "Rolde"}}
    result = run_source(source, wordpress_fetch=lambda *a, **k: ([_raw()], {"total_pages": 1}))
    assert result.events[0].city == "Rolde"


def test_vaste_plek_alleen_voor_podium_in_een_plaats():
    one = {"evidence": [{"kind": "osm", "anchorText": "De Melkfabriek (theatre, Bunne)", "lat": 53.1, "lon": 6.5}]}
    assert default_place_for(one, role="venue") == {"venue": "De Melkfabriek", "city": "Bunne", "lat": 53.1, "lon": 6.5}
    spread = {"evidence": [{"kind": "osm", "anchorText": "Villa (museum, Steenwijk)"},
                           {"kind": "osm", "anchorText": "Huis (museum, Leeuwarden)"}]}
    assert default_place_for(spread, role="venue") is None
    assert default_place_for(one, role="organizer") is None
    assert default_place_for({"evidence": [{"kind": "osm", "anchorText": "Akerk (events_venue)"}]}, role="venue") is None


def test_coordinaten_van_de_plaats_worden_opgezocht():
    class Hit:
        type, label, lat, lon = "woonplaats", "Bunne, Tynaarlo, Drenthe", 53.13, 6.53
    located = locate_city(_raw(city="Bunne"), geocode_fn=lambda q, rows, timeout: [Hit()])
    assert (located.lat, located.lon) == (53.13, 6.53)

    class Street(Hit):
        type = "adres"
    assert locate_city(_raw(city="Bunne"), geocode_fn=lambda q, rows, timeout: [Street()]).lat is None


def test_coordinaten_uit_openstreetmap_blijven_bewaard():
    found = {"url": "https://podium.example/", "kind": "osm", "source_id": "osm:node/1", "lat": 53.2, "lon": 6.5}
    first = merge_candidates([], [dict(found, lat=None, lon=None)])
    again = merge_candidates(first, [found])
    assert (again[0]["evidence"][0]["lat"], again[0]["evidence"][0]["lon"]) == (53.2, 6.5)


def test_lege_wordpress_agenda_telt_niet_als_bron():
    class Page:
        def __init__(self, url, text, ctype="text/html"):
            self.url, self.status, self.content_type, self.text = url, 200, ctype, text

    def fetcher(url, timeout):
        if "wp-json" in url:
            return Page(url, json.dumps({"events": []}), "application/json")
        if url.endswith("robots.txt"):
            return Page(url, "", "text/plain")
        return Page(url, "<html></html>")

    result = probe.probe_source("https://leeg.example/", fetcher=fetcher)
    assert "wordpress_tribe" not in result.extractors
