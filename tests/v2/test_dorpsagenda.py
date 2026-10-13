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
                  "2e Adventsdienst in de Andreaskerk", "Proefrepetitie kerstkoor", "Nieuws uit Terherne",
                  "Koopzondag 6 december", "Hemelvaartsdag", "Optie Andrea", "Banketstavenactie"):
        assert not_an_outing({"title": title}), title
    for title in ("Herfstvakantie: knutselen voor kinderen", "Concert in de grote zaal", "Kerstconcert",
                  "Koningsdag", "Nieuwjaarsduik", "Verkeersregels opfrissen"):
        assert not_an_outing({"title": title}) is None, title


def test_dorpsactiviteiten_krijgen_een_soort():
    expected = {"Koersbal": "sport", "Damesgymclub": "sport", "Yoga in het dorpshuis": "sport",
                "Kerstbingo": "feest", "Pubquiz": "feest", "Klaverjassen": "feest", "Dansmiddag": "feest",
                "Samen koffiedrinken": "eten", "Doarpslunch in MFC": "eten", "Frietavond": "eten",
                "Brei- en haakcafé": "lezing", "Literatuurclub": "lezing", "Volkszang": "muziek",
                "Jamsessie": "muziek", "Speel je mee ochtend": "kinderen", "Zwerfvuil inzamelen": "natuur",
                "Krystmerk": "markt", "Koffieconcert met strijkkwartet": "muziek", "Dobbe spokentocht": "feest",
                "Ladies night": "feest", "Dorpsetentje": "eten", "Verhalenavond": "lezing", "Paasvuur": "feest",
                "Presentatie schetsplan dorpstuin": "lezing", "Fiets daagse": "natuur"}
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


def test_lijst_zonder_jaartallen_over_meer_dan_een_jaar_is_een_archief():
    # Elke maand 'Even bieproaten', van nieuw naar oud: zonder jaartallen klopt het jaar dan niet.
    months = ["december", "november", "oktober", "september", "augustus", "juli", "juni", "mei", "april",
              "maart", "februari", "januari", "december", "november"]
    lines = "<br>".join(f"Even bieproaten: 26 {m}" for m in months)
    assert parse_line_agenda(f"<h2>Agenda 2026</h2><p>{lines}</p>", "https://dorp.example/agenda/", today=TODAY) == []


def test_uitjes_verder_dan_anderhalf_jaar_vooruit_zijn_een_leesfout(tmp_path):
    import json
    from pipeline.v2.build import build
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    rows = [{"id": i, "title": t, "startDate": d, "city": "Eenrum", "verificationStatus": "organizer_confirmed",
             "eventUrl": f"https://dorp.example/{i}", "sourceUrl": f"https://dorp.example/{i}"}
            for i, t, d in (("a", "Kerstmarkt", "2026-12-12"), ("b", "Dorpsfeest", "2033-08-28"))]
    (data / "events.json").write_text(json.dumps(rows))
    events, status = build(data, out, TODAY, {}, photo_cache={})
    assert [e["title"] for e in events] == ["Kerstmarkt"] and status["teVerVooruit"] == 1


def test_clubs_bestuur_en_vaste_ontmoetingen_zijn_geen_uitje():
    for title in ("50 plus club", "50-Plus", "Jirnsum60Plus Gezellige middag", "Dorpsbelangen", "Doarpsbelang Bitgum",
                  "Inloopmiddag", "De Huiskamer", "Bestuur Bastogne DB", "1dagsbestuur Vrouwen van deze Tijd",
                  "Blomme-aksje VV Suameer", "Frijwilligersjûn VV Suameer", "NL-doet.", "Kerstavond-dienst",
                  "2DE PAASDAG", "Kerst 2026", "Koop nu jullie kaartjes en beleef de magie!", "Evenement type",
                  "21:00 'd Aole School Hoofdstraat 21"):
        assert not_an_outing({"title": title}), title
    for title in ("Dansavond 50 plus", "Dorpsbelangen nieuwjaarsreceptie", "Inloopmiddag met lezing over de Waddenzee",
                  "Kerstconcert 2026", "Ouderensoosreis naar Giethoorn met boottocht"):
        assert not_an_outing({"title": title}) is None, title


def test_de_pagina_van_een_zaal_is_geen_uitje():
    assert not_an_outing({"title": "De Hoeksteen", "url": "https://dorp.example/locations/de-hoeksteen/"})
    # Een uitje met een eigen naam dat naar de zaal linkt, blijft staan.
    assert not_an_outing({"title": "Kerst Pubquiz", "url": "https://dorp.example/locations/t-dorpshuus-nijroon/"}) is None


def test_meer_dorpsactiviteiten_krijgen_een_soort():
    expected = {"17 oktober Hartveilig dag": "lezing", "Buurtbakje": "eten", "Dorpstafel": "eten",
                "Jongeren: Boobytrapbos": "kinderen", "DOE-middag - Herfststuk maken": "lezing",
                "Doarpskeamer + Kledingreparatie": "lezing", "GGG Koken": "eten", "Vrouwencafé": "lezing",
                "Ite & sa": "eten", "November Winds, de Bazuin Stynsgea": "muziek", "BOOMSNOEIDAG": "natuur",
                "Fiets 4-daagse 2027": "natuur", "Avondvierdaagse": "natuur", "Kledingruil": "markt"}
    assert {title: classify({"title": title})["kind"] for title in expected} == expected


def test_de_rubriek_in_de_link_telt_als_soort_van_de_organisator():
    verdict = classify({"title": "Pareltjes uit de werkgemeenschap",
                        "url": "https://kerk.example/cursusprogramma/2118-pareltjes-uit-de-werkgemeenschap"})
    assert verdict["kind"] == "lezing" and verdict["method"] == "organisator"
    assert classify({"title": "Wij zijn de tijden", "url": "https://kerk.example/cursusprogramma"})["kind"] == "lezing"
    # Het laatste stuk van de link is de naam van het uitje zelf, geen rubriek.
    assert classify({"title": "Eka", "url": "https://dorp.example/event/eka-9/"})["kind"] == "overig"


def test_losse_aanduiding_achter_de_naam_en_postcode_voor_de_plaats():
    from pipeline.v2.convert import clean_title, to_v2
    assert clean_title("Durf moedig te zijn Start") == "Durf moedig te zijn"
    assert clean_title("Valse Start") == "Valse Start"
    row = {"title": "Kerstmarkt", "startDate": "2026-12-12", "city": "9341 BL Veenhuizen",
           "verificationStatus": "organizer_confirmed", "eventUrl": "https://dorp.example/kerstmarkt"}
    assert to_v2(row, TODAY)["venue"]["city"] == "Veenhuizen"


def test_kaartje_van_events_manager_geeft_de_echte_naam():
    # Een kaartje dat helemaal een link is: datum, tijdvak en rubrieken bovenaan, de naam vet eronder.
    card = ('<a href="https://mfc.example/evenement/{slug}/" class="em-event em-item">'
            '<div class="em-item-top-info"><div class="date"><span>{day}</span> <span>oktober</span> <span>2026</span></div>'
            '<div class="time">{time}</div><div class="em-item-categories">Culturele Commissie, Muziek</div></div>'
            '<div class="em-item-bottom-info"><strong class="em-item-title">{title}</strong>'
            '<span>Meer info</span></div></a>')
    html = "<div>" + "".join(card.format(slug=s, day=d, time=t, title=n) for s, d, t, n in (
        ("adri", 23, "20:00 &#8211; 22:15", "Adri de Boer zingt Stef Bos"),
        ("thee", 24, "14:00 &#8211; 16:00", "Japanse theeproeverij"),
        ("bord", 30, "19:30 &#8211; 22:00", "Bordspelavond voor jong en oud"))) + "</div>"
    events = parse_line_agenda(html, "https://mfc.example/", today=TODAY)
    assert [(e.title, e.start_date, e.time_text) for e in events] == [
        ("Adri de Boer zingt Stef Bos", "2026-10-23", "20:00"),
        ("Japanse theeproeverij", "2026-10-24", "14:00"),
        ("Bordspelavond voor jong en oud", "2026-10-30", "19:30")]


def test_een_tijdvak_is_geen_naam():
    from collector.dutch_agenda_html import parse_agenda
    html = ('<article><h3>Kaboutertocht</h3><p>18 oktober 2026</p><p>10:30 tot 16:00</p>'
            '<a href="https://borg.example/agenda/kaboutertocht/">Meer info</a></article>'
            '<article><h3>14:30 TOT 15:30</h3><p>16 oktober 2026</p></article>')
    titles = [e.title for e in parse_agenda(html, "https://borg.example/agenda/", today=TODAY)]
    assert "Kaboutertocht" in titles and not any("TOT" in t for t in titles)


def test_tijd_voor_de_naam_en_kopjes_van_een_agenda():
    from pipeline.v2.convert import clean_title
    assert clean_title("16:00 Kerstmarkt") == "Kerstmarkt"
    assert clean_title("20:00 - 22:00 Concert") == "Concert"
    assert clean_title("14:30 TOT 15:30") == "14:30 TOT 15:30"   # alleen een tijdvak: zie hieronder
    for title in ("14:30 TOT 15:30", "Culturele Commissie, Muziek", "Algemeen", "Activiteiten, Algemeen",
                  "Aankomende evenementen", "Informatie", "Tijd en", "Dorpsagenda", "Evenementgegevens",
                  "Breng je evenement onder de aandacht!", "'d Aole School Hoofdstraat 21", "Gebiedsregisseur"):
        assert not_an_outing({"title": title}), title
    assert not_an_outing({"title": "De Hoeksteen", "venue": {"name": "De Hoeksteen"}})
    assert not_an_outing({"title": "Kerstmarkt", "venue": {"name": "De Hoeksteen"}}) is None
    # Een tournee met alleen de plaats als zaal blijft staan.
    assert not_an_outing({"title": "Drachten", "venue": {"name": "Drachten", "city": "Drachten"}}) is None


def test_nog_meer_dorpsactiviteiten_krijgen_een_soort():
    expected = {"Westerlee 1 - SV Mussel 1": "sport", "Fitness": "sport", "Kampioensweekend trial": "sport",
                "Cellist Alistair Sung": "muziek", "Accordeoniste Erica Roozendaal": "muziek",
                "Lessons and Carols - kamerkoor Northern Voices": "muziek", "Elvis Tribute": "muziek",
                "Huiskamerpodium Sleen en omgeving": "muziek", "De leafde begrave – TC Teater": "theater",
                "De Lytse Komeedzje": "theater", "Cultuurmiddag in Studio to B": "kunst",
                "Geschiedenis van het boerendorp": "kunst", "Winterbuffet": "eten", "Heel Spijk Bakt": "eten",
                "Spieksters aan toavel": "eten", "Kerststukje maken": "lezing", "Pompoenen uithollen": "kinderen",
                "90-jarig jubileum CSVO": "feest", "Neut’n Schait’n": "feest",
                "Inloopdag schade-energie-subsidies-informatie": "lezing", "Adri de Boer zingt Stef Bos": "muziek",
                "Bordspelavond voor jong en oud": "feest", "Modelbouwdag": "markt",
                "Tjep kookt met de dames van Onder de Pannen": "eten"}
    assert {title: classify({"title": title})["kind"] for title in expected} == expected
