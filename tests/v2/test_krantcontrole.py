"""Lessen uit de krantencontrole (Eemsbode, oktober 2026): robots.txt met een lege User-agent, kaartjes met
een paginanummer in het pad en een plek per kaartje, en gegevens met een plek per uitje."""
from datetime import date
from urllib.robotparser import RobotFileParser

from collector import html_cards
from collector.site_crawler import USER_AGENT, Fetched, clean_robots
from collector.json_api_events import parse_items


def _robots(text):
    rp = RobotFileParser()
    rp.parse(clean_robots(text.splitlines()))
    return rp


def test_lege_user_agent_sluit_niet_iedereen_uit():
    rp = _robots("User-agent:\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert rp.can_fetch(USER_AGENT, "https://www.dorpskerkharen.nl/agenda")
    # Een gewone blokkade blijft gewoon gelden.
    assert not _robots("User-agent: *\nDisallow: /\n").can_fetch(USER_AGENT, "https://x.nl/")
    # Een lege regel naast een echte naam in dezelfde groep: de echte naam telt.
    rp = _robots("User-agent:\nUser-agent: UITNU-Crawler\nDisallow: /geheim\n")
    assert not rp.can_fetch(USER_AGENT, "https://x.nl/geheim") and rp.can_fetch(USER_AGENT, "https://x.nl/agenda")


def test_geen_discovery_in_de_naam():
    assert "discovery" not in USER_AGENT.lower()


CARD = ('<article class="kaart"><h2>{t}</h2><span class="d">za 24 okt 2026 20:00</span>'
        '<span class="p">{p}</span><a href="/x/{n}">x</a></article>')


def test_paginanummer_in_het_pad_en_plaats_per_kaartje():
    pages = {
        "https://k.nl/act/0": CARD.format(t="Orgelconcert", p="Garnwerd", n=1),
        "https://k.nl/act/1": CARD.format(t="Lezing", p="Tolbert", n=2),
        "https://k.nl/act/2": "<p>niets</p>",
    }
    seen = []

    def fake(url, timeout=15):
        seen.append(url)
        if url.endswith("robots.txt"):
            return Fetched(url=url, status=404, content_type="text/plain", text="")
        return Fetched(url=url, status=200, content_type="text/html", text=pages.get(url, ""))

    config = {"endpointUrl": "https://k.nl/act/{page}", "firstPage": 0, "maxPages": 5, "card": r"<article",
              "fields": {"title": r"<h2>(.*?)</h2>", "date": r'class="d">(.*?)<', "city": r'class="p">(.*?)<',
                         "url": r'href="([^"]+)"'}}
    events = html_cards.fetch(config, source_name="k", root_url="https://k.nl/", page_fetch=fake,
                              today=date(2026, 10, 19))
    assert [(e.title, e.city) for e in events] == [("Orgelconcert", "Garnwerd"), ("Lezing", "Tolbert")]
    assert "https://k.nl/act/0" in seen and "https://k.nl/act/3" not in seen


def test_gegevens_met_een_plek_per_uitje():
    data = {"features": [{"properties": {"name": "Nacht van de Nacht", "date": "2026-10-24", "location": "Onbekend bos"},
                          "geometry": {"coordinates": [6.31, 52.95]}}]}
    config = {"items": "features", "title": "properties.name", "startDate": "properties.date",
              "venue": "properties.location", "lat": "geometry.coordinates.1", "lon": "geometry.coordinates.0"}
    [event] = parse_items(data, config, source_name="gl", root_url="https://gl.nl/", today=date(2026, 10, 19))
    assert (event.venue, event.lat, event.lon) == ("Onbekend bos", 52.95, 6.31)
