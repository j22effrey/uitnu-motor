"""Agenda's van dorpshuizen: vaste activiteiten, zaalverhuur en oude pagina's zijn geen uitjes."""
from datetime import date, timedelta

from collector.dutch_agenda_html import parse_line_agenda
from pipeline.v2.build import routines
from pipeline.v2.classify import classify, not_an_outing

TODAY = date(2026, 10, 12)


def _event(title, day, kind, host="dorpshuis.example"):
    return {"title": title, "kind": kind, "occurrences": [{"date": day.isoformat()}],
            "sources": [{"type": "organisator", "url": f"https://{host}/agenda", "host": host}]}


def test_elke_week_dezelfde_clubavond_is_geen_uitje():
    start = date(2026, 10, 13)
    events = [_event(f"Jeu de boules van {14 + i % 2}:00 tot 16:00 uur", start + timedelta(weeks=i), "sport") for i in range(6)]
    events += [_event("Klaverjassen", start + timedelta(weeks=i), "feest") for i in range(5)]
    events += [_event("CATS", start + timedelta(days=i), "theater", "theater.example") for i in range(6)]   # blijft
    events += [_event("Dorpsfeest", start, "feest"), _event("Pubquiz", start + timedelta(days=60), "feest")]
    events += [_event(f"Artiest {i}", start, "overig", "podium.example") for i in range(6)]                # zelfde dag
    dropped = {events[i]["title"] for i in routines(events)}
    assert dropped == {"Jeu de boules van 14:00 tot 16:00 uur", "Jeu de boules van 15:00 tot 16:00 uur", "Klaverjassen"}
    # Eens per maand is geen vaste weekactiviteit.
    monthly = [_event("Bingo", start + timedelta(days=30 * i), "feest") for i in range(5)]
    assert routines(monthly) == set()


def test_zaalverhuur_afval_en_kopjes_zijn_geen_uitje():
    for title in ("Bezet", "Verhuur grote zaal", "Afval grijze container restafval", "Digitaal spreekuur",
                  "Repetitie Harmonie", "Verenigingenoverleg", "Startdatum", "Grote zaal (bezet)",
                  "Eerste kerstdag", "Kerstvakantie regio noord", "Bijeenkomst vrouwenvereniging", "Oudpapier",
                  "2e Adventsdienst in de Andreaskerk"):
        assert not_an_outing({"title": title}), title
    for title in ("Herfstvakantie: knutselen voor kinderen", "Concert in de grote zaal", "Kerstconcert"):
        assert not_an_outing({"title": title}) is None, title


def test_dorpsactiviteiten_krijgen_een_soort():
    expected = {"Koersbal": "sport", "Damesgymclub": "sport", "Yoga in het dorpshuis": "sport",
                "Kerstbingo": "feest", "Pubquiz": "feest", "Klaverjassen": "feest", "Dansmiddag": "feest",
                "Samen koffiedrinken": "eten", "Doarpslunch in MFC": "eten", "Frietavond": "eten",
                "Brei- en haakcafé": "lezing", "Literatuurclub": "lezing", "Volkszang": "muziek",
                "Jamsessie": "muziek", "Speel je mee ochtend": "kinderen", "Zwerfvuil inzamelen": "natuur",
                "Krystmerk": "markt", "Koffieconcert met strijkkwartet": "muziek"}
    assert {title: classify({"title": title})["kind"] for title in expected} == expected


def test_agenda_van_een_vorig_jaar_of_zonder_jaar_levert_niets_op():
    lines = "<p>Spooktocht: 13 november<br>Kerstmarkt: 12 december<br>Nieuwjaarsduik: 1 januari</p>"
    # Een pagina over 2024: die data zijn voorbij, ook al staat er geen jaar bij.
    assert parse_line_agenda(lines, "https://dorp.example/activiteiten-2024/", today=TODAY) == []
    # Geen jaar en geen weekdag, en de pagina noemt dit jaar niet: niet te controleren.
    assert parse_line_agenda(lines, "https://dorp.example/agenda/", today=TODAY) == []
    # Noemt de pagina dit jaar wel, dan gaat het goed.
    events = parse_line_agenda("<h2>Agenda 2026</h2>" + lines, "https://dorp.example/agenda/", today=TODAY)
    assert [(e.title, e.start_date) for e in events] == [
        ("Spooktocht", "2026-11-13"), ("Kerstmarkt", "2026-12-12"), ("Nieuwjaarsduik", "2027-01-01")]
