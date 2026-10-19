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


def test_alleen_een_lege_user_agent_blijft_een_blokkade():
    assert not _robots("User-agent:\nDisallow: /\n").can_fetch(USER_AGENT, "https://x.nl/agenda")


def test_plaats_met_dezelfde_naam_in_de_provincie_van_de_bron():
    from types import SimpleNamespace
    from collector.title_place_inference import locate_city
    from pipeline.event_model import RawEvent

    def pdok(name, rows=6, timeout=8):
        return [SimpleNamespace(type="woonplaats", label="Zuidwolde, De Wolden, Drenthe", lat=52.67, lon=6.43),
                SimpleNamespace(type="woonplaats", label="Zuidwolde, Het Hogeland, Groningen", lat=53.26, lon=6.59)]

    event = RawEvent(source_name="k", source_type="structured_web", source_url="https://k.nl/", source_id=None,
                     title="Klankkoor", start_at="2026-10-25", city="Zuidwolde", raw={"provincie": "Groningen"})
    assert locate_city(event, geocode_fn=pdok).lat == 53.26
    zonder = RawEvent(source_name="k", source_type="structured_web", source_url="https://k.nl/", source_id=None,
                      title="Klankkoor", start_at="2026-10-25", city="Zuidwolde", raw={})
    assert locate_city(zonder, geocode_fn=pdok).lat == 52.67


def test_bluesclub_is_een_optreden_geen_clubavond():
    from pipeline.v2.classify import not_an_outing
    assert not_an_outing({"title": "Bluesclub Kielzog"}) is None
    assert not_an_outing({"title": "Jazzclub: Shuteen Erdenebaatar Quartet"}) is None
    assert not_an_outing({"title": "Biljartclub"})


def test_html_tekens_in_de_naam_en_een_kopje_als_naam():
    from pipeline.v2.classify import not_an_outing
    from pipeline.v2.convert import clean_title
    assert clean_title("Film avond &#8211; 29 oktober") == "Film avond – 29 oktober"
    assert clean_title("Bok &amp; Najaars Bierentocht") == "Bok & Najaars Bierentocht"
    assert clean_title("Kunst&centrum open dag") == "Kunst&centrum open dag"
    assert not_an_outing({"title": "Over dit evenement"})
    assert not_an_outing({"title": "Filmclub seizoen 2026 | 2027"})
    assert not_an_outing({"title": "Filmclub: Perfect Days"}) is None
    assert not_an_outing({"title": "Over de rivier, een voorstelling"}) is None


def test_tabel_met_een_periode_loopt_door_tot_de_laatste_dag():
    from collector.dutch_agenda_html import parse_table_agenda
    html = ("<p>Programma Zuidlaardermarkt 2026</p><table><tr><th>Datum</th><th>Tijd</th><th>Activiteit</th></tr>"
            "<tr><td>16 oktober</td><td>19.00 uur</td><td>Opening kermis</td></tr>"
            "<tr><td>16 tot en met 20 oktober</td><td>Vanaf 20.00 uur</td><td>Livemuziek in feesttent</td></tr></table>")
    events = {e.title: e for e in parse_table_agenda(html, "https://x.nl/programma", today=date(2026, 10, 19))}
    assert events["Livemuziek in feesttent"].start_date == "2026-10-16"
    assert events["Livemuziek in feesttent"].end_date == "2026-10-20"
    assert events["Opening kermis"].end_date is None
