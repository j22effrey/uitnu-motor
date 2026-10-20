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


def test_periode_in_regels_en_kaartjes_loopt_door():
    from collector.dutch_agenda_html import extract_blocks, parse_line_agenda
    from collector.when import parse_end_day
    assert parse_end_day("17 okt t/m 18 okt 2026", "2026-10-17") == "2026-10-18"
    assert parse_end_day("vr 16 - zo 18 oktober", "2026-10-16") == "2026-10-18"
    assert parse_end_day("28 december t/m 3 januari", "2026-12-28") == "2027-01-03"
    assert parse_end_day("za 17 okt 20:00 - 23:00", "2026-10-17") is None
    html = ("<ul><li>Kunstroute Paterswolde: 16 t/m 25 oktober</li><li>Lezing over vogels: 12 november</li>"
            "<li>Kerstconcert: 20 december</li></ul><p>Agenda 2026</p>")
    events = {e.title: e for e in parse_line_agenda(extract_blocks(html, "https://x.nl/"), "https://x.nl/",
                                                    today=date(2026, 10, 19))}
    assert events["Kunstroute Paterswolde"].end_date == "2026-10-25"
    assert events["Lezing over vogels"].end_date is None
    card = '<article><h2>Fruit- en Snoeidagen</h2><div class="date">17 okt t/m 18 okt 2026</div></article>'
    [event] = html_cards.parse_cards(card, {"card": "<article", "fields": {"title": "<h2>(.*?)</h2>",
                                     "date": 'class="date">(.*?)</div>'}}, source_name="t", page_url="https://t.nl/",
                                     today=date(2026, 10, 17))
    assert (event.start_at, event.end_at) == ("2026-10-17", "2026-10-18")


def test_studievereniging_wordt_geen_bron():
    from collector.auto_activate import eligible
    base = {"probeStatus": "supported", "robotsStatus": "allowed", "url": "https://www.svscopus.nl/"}
    assert not eligible({**base, "name": "Studievereniging Scopus"})
    assert not eligible({**base, "name": "Studentenvereniging Vindicat"})
    assert eligible({**base, "name": "Muziekvereniging Concordia", "url": "https://concordia.example/"})


def test_periode_begint_op_de_eerste_dag_en_nachtfeest_is_een_avond():
    from collector.when import parse_end_day, parse_when
    today = date(2026, 10, 19)
    assert parse_when("02 - 06 nov 2026", today=today) == "2026-11-02"
    assert parse_end_day("02 - 06 nov 2026", "2026-11-02") == "2026-11-06"
    assert parse_end_day("vr 16 okt 23:00 - za 17 okt 04:00", "2026-10-16") is None
    assert parse_when("20:30 - 22 oktober", today=today) != "2026-10-30"


def test_film_blijft_film_bij_samenvoegen():
    from pipeline.v2.convert import merge_duplicates
    base = {"title": "La Vita Va Così", "venue": {"name": "De Winsinghhof", "city": "Roden"}, "price": None,
            "occurrences": [{"date": "2026-11-03", "startTime": "20:00"}], "tags": [], "url": None}
    theater = {**base, "schemaType": "TheaterEvent", "sources": [{"url": "https://theaterroden.nl/voorstelling/1"}]}
    film = {**base, "schemaType": "ScreeningEvent", "sources": [{"url": "https://theaterroden.nl/la-vita"}],
            "occurrences": [{"date": "2026-11-03", "startTime": "20:00"}]}
    [merged] = merge_duplicates([theater, film])
    assert merged["schemaType"] == "ScreeningEvent"


def test_stripshow_is_geen_uitje_voor_iedereen():
    from pipeline.v2.classify import not_an_outing
    assert not_an_outing({"title": "Thunder From Down Under – De ultieme Ladies Night Out!! (18+)"})
    assert not_an_outing({"title": "Ladies Night"}) is None


def test_robots_langste_regel_telt_zoals_rfc_9309():
    """Vera: 'Disallow: /wp/wp-admin/' en daarna 'Allow: /wp/wp-admin/admin-ajax.php'. Python 3.12 nam de eerste
    regel en weigerde het programma; volgens RFC 9309 telt de langste regel (oktober 2026)."""
    from collector.site_crawler import parse_robots
    rp = RobotFileParser()
    parse_robots(rp, "User-agent: *\nDisallow: /wp/wp-admin/\nAllow: /wp/wp-admin/admin-ajax.php\n".splitlines())
    assert rp.can_fetch(USER_AGENT, "https://v.nl/wp/wp-admin/admin-ajax.php?action=renderProgramme")
    assert not rp.can_fetch(USER_AGENT, "https://v.nl/wp/wp-admin/options.php")
    rp = RobotFileParser()
    parse_robots(rp, "User-agent: *\nAllow: /\nDisallow: /geheim\n".splitlines())
    assert not rp.can_fetch(USER_AGENT, "https://v.nl/geheim/x") and rp.can_fetch(USER_AGENT, "https://v.nl/agenda")
    # Met een jokerteken ('*' of '$', dat Python 3.12 niet kent) blijft de strengere volgorde: nooit iets
    # ophalen wat de website verbiedt.
    rp = RobotFileParser()
    parse_robots(rp, "User-agent: *\nDisallow: /\nAllow: /agenda\nDisallow: /agenda/*?print\n".splitlines())
    assert not rp.can_fetch(USER_AGENT, "https://v.nl/agenda/x?print=1")
