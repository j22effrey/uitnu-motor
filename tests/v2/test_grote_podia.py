"""Grote podia: agenda's van kaartjes, gegevens met losse datum en tijd, bladeren en datums in allerlei vormen."""
import json
from datetime import date

from collector import html_cards, json_api_events
from collector.site_crawler import Fetched, _load_robots
from collector.when import parse_time, parse_when

TODAY = date(2026, 10, 16)


def test_datums_en_tijden_in_allerlei_vormen():
    assert parse_when("2026-10-16T20:00:00+02:00", today=TODAY) == "2026-10-16T20:00"
    assert parse_when("2026-10-17 00:00:00.000000", "19.30 - 23.00 uur", today=TODAY) == "2026-10-17T19:30"
    assert parse_when(1792713600, "20:00", today=TODAY) == "2026-10-23T20:00"           # getal (WordPress)
    assert parse_when("za 17 okt 2026", "09:00 & 10:30", today=TODAY) == "2026-10-17T09:00"
    assert parse_when("do 15.10", today=TODAY) == "2026-10-15"                         # Simplon
    assert parse_when("do 5.11", today=TODAY) == "2026-11-05"
    assert parse_when("Saturday 6 November", "Mainstage | doors: 20:00 | start: 20:30", today=TODAY) == "2027-11-06T20:30"
    assert parse_when("Thursday 15 October", today=TODAY) == "2026-10-15"
    assert parse_when("16-10-2026 / 10:00", today=TODAY) == "2026-10-16T10:00"
    assert parse_when("Sat 28 Nov 2026 // 15:00", today=TODAY) == "2026-11-28T15:00"
    # Een weekdag die bij geen jaar past: liever niets dan een verkeerde dag.
    assert parse_when("ma 15.10", today=TODAY) is None
    assert parse_when("binnenkort", today=TODAY) is None
    assert parse_time("doors: 20:00 | start: 20:30") == "20:30" and parse_time("Kelderbar") is None


SPOT = """
<article class="program__item" data-genres="muziek" data-location="oosterpoort">
  <a href="https://www.spotgroningen.nl/programma/grandmaster-flash/"><h3>Grandmaster Flash</h3>
  <time datetime="2026-10-16T20:00:00+02:00">vr 16 okt</time></a></article>
<article class="program__item" data-genres="familie" data-location="stadsschouwburg">
  <a href="/programma/kluizelaar/"><h3>Kluizelaar (2 - 7)<span>Simone de Jong Company</span></h3>
  <time datetime="2026-10-17T11:00:00+02:00">za 17 okt</time></a></article>
<article class="program__item" data-genres="" data-location="oosterpoort">
  <a href="/programma/abonnement-x/"><h3>Abonnement Klassiek</h3><time datetime="2026-10-18T20:00:00+02:00"></time></a></article>
"""
SPOT_CFG = {"card": '<article class="program__item', "skipTitle": "^abonnement",
            "fields": {"title": "<h3[^>]*>((?:(?!<span|</h3>).)*)", "extra": "<h3[^>]*>(?:(?!</h3>).)*?<span[^>]*>(.*?)</span>",
                       "start": '<time[^>]*datetime="([^"]+)"', "url": '<a[^>]*href="([^"]+)"',
                       "genre": 'data-genres="([^"]*)"', "room": 'data-location="([^"]*)"'},
            "rooms": {"stadsschouwburg": {"venue": "Stadsschouwburg", "city": "Groningen", "lat": 53.22, "lon": 6.57}},
            "genres": {"muziek": "MusicEvent", "familie": "ChildrensEvent"}}


def test_kaartjes_spot():
    events = html_cards.parse_cards(SPOT, SPOT_CFG, source_name="SPOT", page_url="https://www.spotgroningen.nl/programma/", today=TODAY)
    assert [e.title for e in events] == ["Grandmaster Flash", "Kluizelaar (2 - 7) – Simone de Jong Company"]
    assert events[0].start_at.startswith("2026-10-16T20:00") and events[0].category == "MusicEvent" and events[0].venue is None
    second = events[1]
    assert (second.venue, second.city, second.lat, second.category) == ("Stadsschouwburg", "Groningen", 53.22, "ChildrensEvent")
    assert second.source_url == "https://www.spotgroningen.nl/programma/kluizelaar/"


VERA = """
<div class="col-xs-60 event-wrapper"><a class="event-link vert-aligneable-container " href="https://www.vera-groningen.nl/?p=1">
 <div class="date"><h4 class="pretitle">Vera</h4> Friday 16 October </div><h3 class="artist ">Kelderbar Open<sup class="origin "></sup></h3>
 <div class="schedule"></div></a></div>
<div class="col-xs-60 event-wrapper"><a class="event-link vert-aligneable-container concert" href="https://www.vera-groningen.nl/?p=2">
 <div class="date"> Saturday 6 November </div><h3 class="artist ">Bettie Serveert<sup class="origin ">NL</sup></h3><h4 class="extra">The Monroes</h4>
 <div class="schedule">Mainstage | Ticket: €13,- | doors: 20:00 - 22:00 | start: 20:30</div></a></div>
"""
VERA_CFG = {"card": '<div class="[^"]*event-wrapper', "dropFromTitle": "<sup.*?</sup>", "skipTitle": "^kelderbar",
            "fields": {"title": '<h3 class="artist[^"]*">(.*?)</h3>', "extra": '<h4 class="extra[^"]*">(.*?)</h4>',
                       "date": '<div class="date">(?:\\s*<h4[^>]*>.*?</h4>)?(.*?)</div>', "time": '<div class="schedule">(.*?)</div>',
                       "url": 'class="event-link[^"]*"\\s*href="([^"]+)"', "genre": 'event-link vert-aligneable-container\\s*([a-z-]*)\\s*"'},
            "genres": {"concert": "MusicEvent"}}


def test_kaartjes_vera_engels_zonder_jaar():
    events = html_cards.parse_cards(VERA, VERA_CFG, source_name="Vera", page_url="https://www.vera-groningen.nl/", today=TODAY)
    assert len(events) == 1  # de bar die open is, is geen uitje
    assert (events[0].title, events[0].start_at, events[0].category) == ("Bettie Serveert – The Monroes", "2027-11-06T20:30", "MusicEvent")


FORUM_ROW = """<div class="ticket-row"><a data-program-id="{id}" data-title="{title}" href="https://forum.nl/nl/agenda/{slug}?date=16-10-2026" class="link-event"></a>
<div class="tag-wrapper"><span class="tag"> {tag} </span></div><div class="time item"><p> 10:00 <span class="space">-</span> 11:18 </p></div></div>"""


def test_bladeren_tot_een_lege_of_herhaalde_pagina():
    pages = {1: FORUM_ROW.format(id=1, title="Lotte (4&#x2B;)", slug="lotte", tag="Kinderfilm")
                + FORUM_ROW.format(id=2, title="Inloopspreekuur", slug="spreekuur", tag="Spreekuur"),
             2: FORUM_ROW.format(id=3, title="Menno de Bree", slug="menno", tag="Talk"),
             3: FORUM_ROW.format(id=3, title="Menno de Bree", slug="menno", tag="Talk")}  # negeert het paginanummer
    asked = []

    def fetch(url, timeout=15):
        if url.endswith("robots.txt"):
            return Fetched(url=url, status=404, content_type="text/plain", text="")
        asked.append(url)
        page = int(url.rsplit("p=", 1)[1])
        return Fetched(url=url, status=200, content_type="text/html", text=pages.get(page, ""))

    cfg = {"endpointUrl": "https://forum.nl/nl/agenda?locatie=forum-groningen", "pageParam": "p", "maxPages": 10,
           "card": '<div class="ticket-row', "skipTags": "spreekuur",
           "fields": {"title": 'data-title="([^"]+)"', "url": '<a [^>]*href="([^"]+)"[^>]*class="link-event"',
                      "date": "\\?date=(\\d{2}-\\d{2}-20\\d{2})", "time": '<div class="time item">\\s*<p>(.*?)</p>',
                      "end": '<div class="time item">\\s*<p>[^<]*<span[^>]*>-</span>\\s*([0-9:.]+)',
                      "tags": '((?:<span class="tag[^"]*">[^<]*</span>\\s*)+)'},
           "genres": {"Kinderfilm": "ScreeningEvent", "Talk": "EducationEvent"}}
    events = html_cards.fetch(cfg, source_name="Forum", root_url="https://forum.nl/", page_fetch=fetch, today=TODAY)
    assert [e.title for e in events] == ["Lotte (4+)", "Menno de Bree"]
    assert events[0].start_at == "2026-10-16T10:00" and events[0].end_at == "2026-10-16T11:18"
    assert events[0].category == "ScreeningEvent" and "locatie=forum-groningen" in asked[0]
    assert len(asked) == 3


def test_gegevens_met_losse_datum_tijd_overslaan_en_bladeren():
    huizemaas = [{"id": 1, "link": "https://huizemaas.nl/agenda/a", "title": {"rendered": "Cover &#8211; Live"},
                  "meta": {"datum-agenda": 1792713600, "start-tijd": "20:00"}, "agenda-categorie": [120]},
                 {"id": 2, "link": "https://huizemaas.nl/agenda/b", "title": {"rendered": "Oud"},
                  "meta": {"datum-agenda": 1700000000, "start-tijd": "20:00"}, "agenda-categorie": [122]}]
    cfg = {"items": "", "title": "title.rendered", "startDate": "meta.datum-agenda", "startTime": "meta.start-tijd",
           "url": "link", "id": "id", "skipField": "agenda-categorie", "skipValue": "\\b122\\b"}
    events = json_api_events.parse_items(huizemaas, cfg, source_name="Huize Maas", root_url="https://huizemaas.nl/", today=TODAY)
    assert [(e.title, e.start_at) for e in events] == [("Cover – Live", "2026-10-23T20:00")]

    pages = {1: [{"title": "A", "formatted_date": "za 17 okt 2026", "formatted_start_time": "20:30", "url": "/a"}],
             2: [{"title": "B", "formatted_date": "vr 20 nov 2026", "formatted_start_time": "19:30", "url": "/b"}]}
    asked = []

    def json_fetch(url, timeout=15):
        asked.append(url)
        page = int(url.rsplit("page=", 1)[1])
        return json.dumps({"data": pages.get(page, pages[2])})  # na de laatste pagina weer de laatste

    def robots(url, timeout=15):
        return Fetched(url=url, status=404, content_type="text/plain", text="")

    cfg = {"endpointUrl": "https://tumultgroningen.nl/api/v1/activities", "pageParam": "page", "maxPages": 9, "items": "data",
           "title": "title", "startDate": "formatted_date", "startTime": "formatted_start_time", "url": "url"}
    events = json_api_events.fetch(cfg, source_name="Tumult", root_url="https://tumultgroningen.nl/", robots_fetch=robots, json_fetch=json_fetch)
    assert [(e.title, e.start_at) for e in events] == [("A", "2026-10-17T20:30"), ("B", "2026-11-20T19:30")]
    assert len(asked) == 3


def test_robots_als_gewone_niet_gevonden_pagina_is_geen_verbod():
    def soft404(url, timeout=15):
        return Fetched(url=url, status=200, content_type="text/html",
                       text='<html><title>Museum</title>' + 'x' * 30000 + '"notFound":"404: This page could not be found."</html>')

    def antibot(url, timeout=15):
        return Fetched(url=url, status=200, content_type="text/html", text="<html>Just a moment... 404 not found</html>")

    def login(url, timeout=15):
        return Fetched(url=url, status=200, content_type="text/html", text="<html><form>Inloggen</form></html>")

    assert _load_robots("https://www.groningermuseum.nl/", soft404, timeout=5)[0].can_fetch("UITNU", "https://www.groningermuseum.nl/programma")
    assert not _load_robots("https://x.nl/", antibot, timeout=5)[0].can_fetch("UITNU", "https://x.nl/agenda")
    assert not _load_robots("https://x.nl/", login, timeout=5)[0].can_fetch("UITNU", "https://x.nl/agenda")


def test_grote_podia_staan_in_de_bronnenlijst():
    sources = {s["id"]: s for s in json.load(open("collector/web_crawl_sources.json", encoding="utf-8"))["sources"]}
    for sid, hint in [("spot-groningen-web", "html_cards"), ("vera-groningen-web", "html_cards"), ("simplon-nl-web", "html_cards"),
                      ("forum-nl-web", "html_cards"), ("huizemaas-nl-web", "json_api"), ("tumult-groningen-api", "json_api"),
                      ("akerk-nl-api", "json_api")]:
        assert sources[sid]["enabled"] and sources[sid]["extractorHint"] == hint
        assert sources[sid]["extractorConfig"]["endpointUrl"].startswith(sources[sid]["rootUrl"].rstrip("/"))
    # Stager (de kaartverkoop) verbiedt alle bots: nooit als bron.
    assert not any("stager.co" in json.dumps(s) for s in sources.values())
