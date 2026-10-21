"""Oost-Groningen (20 oktober 2026): de kaart was er bijna leeg. Nieuwe bronnen (City Club Winschoten, Blauwestad,
de bibliotheken van Westerwolde en Pekela) vroegen drie dingen van de kaartjeslezer: wachten als robots.txt
daarom vraagt (Crawl-delay), links vanaf <base href>, en een tentoonstelling met een periode én een eindtijd."""
import json
from datetime import date
from pathlib import Path

from collector import html_cards
from collector.site_crawler import Fetched
from pipeline.v2.classify import classify

OVERRIDES = json.loads((Path(__file__).parents[2] / "pipeline" / "v2" / "overrides.json").read_text(encoding="utf-8"))


def _fetcher(pages, robots=""):
    def fake(url, timeout=15):
        if url.endswith("robots.txt"):
            return Fetched(url=url, status=200 if robots else 404, content_type="text/plain", text=robots)
        return Fetched(url=url, status=200, content_type="text/html", text=pages.get(url, ""))
    return fake


CARD = '<div class="kaart"><h3>{t}</h3><span class="d">{d}</span><span class="t">{tijd}</span><a href="{u}">x</a></div>'
CONFIG = {"card": r'<div class="kaart"', "fields": {"title": r"<h3>(.*?)</h3>", "date": r'class="d">(.*?)<',
                                                    "time": r'class="t">(\d+:\d+)', "end": r'class="t">\d+:\d+\s*-\s*(\d+:\d+)',
                                                    "url": r'href="([^"]+)"'}}


def test_links_vanaf_base_href():
    page = '<base href="/">' + CARD.format(t="Duitse Dag", d="31 oktober 2026", tijd="", u="evenementen-5/")
    events = html_cards.fetch({**CONFIG, "endpointUrl": "https://c.nl/evenementen/"}, source_name="c",
                              root_url="https://c.nl/", page_fetch=_fetcher({"https://c.nl/evenementen/": page}),
                              today=date(2026, 10, 20))
    assert events[0].source_url == "https://c.nl/evenementen-5/"


def test_tentoonstelling_houdt_de_periode_ook_met_een_eindtijd():
    page = CARD.format(t="Expo Groetjes uit Westerwolde", d="di 20 okt t/m zo 15 nov 2026", tijd="10:00 - 17:00", u="/expo")
    events = html_cards.parse_cards(page, CONFIG, source_name="b", page_url="https://b.nl/agenda", today=date(2026, 10, 20))
    assert events[0].start_at.startswith("2026-10-20") and events[0].end_at.startswith("2026-11-15")
    # Een gewone avond houdt zijn eindtijd.
    page = CARD.format(t="Pubquiz", d="vr 6 november 2026", tijd="20:00 - 22:00", u="/quiz")
    events = html_cards.parse_cards(page, CONFIG, source_name="b", page_url="https://b.nl/agenda", today=date(2026, 10, 20))
    assert events[0].end_at.startswith("2026-11-06T22:00")


def test_wacht_tussen_paginas_als_robots_txt_dat_vraagt(monkeypatch):
    waits = []
    monkeypatch.setattr(html_cards.time, "sleep", waits.append)
    pages = {f"https://b.nl/agenda/{n}": CARD.format(t=f"Workshop {n}", d=f"{n + 1} november 2026", tijd="", u=f"/w{n}")
             for n in (1, 2)}
    events = html_cards.fetch({**CONFIG, "endpointUrl": "https://b.nl/agenda/{page}", "maxPages": 5}, source_name="b",
                              root_url="https://b.nl/", page_fetch=_fetcher(pages, "User-agent: *\nCrawl-delay: 10\n"),
                              today=date(2026, 10, 20))
    assert len(events) == 2 and len(waits) == 2 and all(9.9 < w <= 10 for w in waits)  # voor pagina 2 en de lege pagina 3
    # Een tweede bron op dezelfde website wacht ook op de vorige bezoeken (de Crawl-delay geldt per website).
    waits.clear()
    html_cards.fetch({**CONFIG, "endpointUrl": "https://b.nl/agenda/{page}", "maxPages": 1}, source_name="b2",
                     root_url="https://b.nl/", page_fetch=_fetcher(pages, "User-agent: *\nCrawl-delay: 10\n"),
                     today=date(2026, 10, 20))
    assert len(waits) == 1 and waits[0] > 9.9
    waits.clear()
    html_cards.fetch({**CONFIG, "endpointUrl": "https://b.nl/agenda/{page}"}, source_name="b", root_url="https://b.nl/",
                     page_fetch=_fetcher(pages), today=date(2026, 10, 20))
    assert waits == []


def test_voorleesuurtje_is_voor_kinderen_en_adrillen_is_een_markt():
    def kind(title):
        return classify({"id": title, "title": title, "occurrences": [{"date": "2026-11-09"}], "sources": []}, OVERRIDES)["kind"]
    assert kind("Voorleesuurtje met juf Bianca") == "kinderen"
    assert kind("Boekstarthalfuurtje") == "kinderen"
    assert kind("Adrillen") == "markt"
    assert kind("Lezing over voorlezen") == "lezing"


def test_dezelfde_lezing_in_meerdere_plaatsen_is_geen_vaste_clubavond():
    """De bibliotheek (één website voor alle vestigingen) houdt dezelfde lezing in Nieuwe Pekela, Winschoten,
    Onstwedde en Leek: een rondgang, geen wekelijkse clubavond (oktober 2026)."""
    from pipeline.v2.build import routines
    def ev(day, city):
        return {"title": "Lunchlezing met Sanne Meijer", "kind": "lezing", "venue": {"city": city},
                "occurrences": [{"date": day}], "sources": [{"host": "ticketing.groningsebibliotheken.nl"}]}
    tour = [ev("2026-10-23", "Nieuwe Pekela"), ev("2026-10-30", "Winschoten"), ev("2026-11-06", "Onstwedde"), ev("2026-11-13", "Leek")]
    assert routines(tour, today=date(2026, 10, 21)) == set()
    weekly = [ev(d, "Leek") for d in ("2026-10-23", "2026-10-30", "2026-11-06", "2026-11-13", "2026-11-20")]
    assert routines(weekly, today=date(2026, 10, 21)) == {0, 1, 2, 3, 4}


def test_peuteruurtje_in_een_paar_vestigingen_blijft_een_vaste_activiteit():
    from pipeline.v2.build import routines
    def ev(day, city):
        return {"title": "Dreumesuurtje", "kind": "kinderen", "venue": {"city": city},
                "occurrences": [{"date": day}], "sources": [{"host": "ticketing.groningsebibliotheken.nl"}]}
    events = [ev("2026-10-22", "Stadskanaal"), ev("2026-10-29", "Onstwedde"), ev("2026-11-05", "Stadskanaal"),
              ev("2026-11-12", "Onstwedde")]
    assert routines(events, today=date(2026, 10, 21)) == {0, 1, 2, 3}
