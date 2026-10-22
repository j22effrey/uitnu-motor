"""Het nalopen van de hele agenda (20 oktober 2026): niet wachten tot de eigenaar iets op een schermafbeelding laat zien.
Vier hulpagenten lazen alle 3.024 uitjes; wat geen uitje was, werd een algemene regel (SWEEP_HEADING, SWEEP_NOT_OUTING)."""
import json
from pathlib import Path

from pipeline.v2.classify import classify, not_an_outing
from pipeline.v2.convert import clean_title

OVERRIDES = json.loads((Path(__file__).parents[2] / "pipeline" / "v2" / "overrides.json").read_text(encoding="utf-8"))


def _event(title):
    return {"title": title, "url": "https://dorp.example/agenda/x", "occurrences": [{"date": "2026-11-01"}],
            "sources": [{"type": "organisator", "url": "https://dorp.example/agenda/x", "host": "dorp.example"}]}


def test_menukopjes_en_knoppen_zijn_geen_uitje():
    for title in ("// Concerten", "0 excursies", "Alle datums", "Event info", "Ontdek alle afstanden", "Nu te zien",
                  "Lêste nijs", "Maandelijkse weergave", "Tickets en info", "Thema: Feest", "Uitgevoerde activiteiten",
                  "Programma overzicht 2026", "Foltz Jaaragenda 2027", "Welkom bij openluchtmuseum De Sûkerei.",
                  "Museum open", "Save the date", "🌈 SAVE THE DATE 🌈", "Wordt verwacht...", "Bestel de serie!",
                  "IN TEN BOER IS ALTIJD WAT TE DOEN", "Doors open 12:30, starts at 13:30", "PubQuiz Datum",
                  "Gereformeerde Kerk Visvliet", "Buningshof Algemeen"):
        assert not_an_outing(_event(title)), title


def test_vrijwilligers_vaste_avonden_en_hulp_zijn_geen_uitje():
    for title in ("PAPIERBAK", "Straatverlichting", "Raads­ver­ga­de­ring", "Sinterklaas journaal",
                  "Lekkere daghap eten voor 17,50!", "Elke zondag t/m donderdag voor 12,50!", "Klusdag",
                  "Voorjaarswerk in de Vlindertuin.", "Vlindertuin Algemeen Werkgroep dagvlinders + libelles",
                  "Najaarsbijeenkomst Plaatselijk Belang Appelscha", "vve bedrijfsverzamelgebouw Scharnegoutum",
                  "Bartoleshûs Spekclub", "Mancave", "Nije Powervrouwen", "Praathuis", "Gezellige Middag",
                  "Biodanza met Kees", "Kaboutervoetbal", "Poëziekring", "Volksdansen", "Start dinsdagavondvaren",
                  "Létste thúswedstrydfeest VV Suameer",
                  "Linux informatie en installatie avond", "Workshop ChatGPT voor beginners", "Workshop Delpher",
                  "Workshop: Cyberveiligheid in begrijpelijke taal", "Pubquiz 50+", "De DigiVitaler - Computercursus",
                  "Check je zorgverzekeraar", "Keuvel, Kovvie en bordspelletjes", "Workshop Digitale Nalatenschap",
                  "Anders vieren dienst m.m.v. Rokus Maasland/ The Bowery"):
        assert not_an_outing(_event(title)), title


def test_echte_uitjes_blijven_staan():
    for title in ("Natuurwerkdag Buningshof", "Jeugdworkshop Vogelkastjes timmeren Buningshof", "Concerten in de kerk",
                  "Sinterklaasintocht Meeden", "Pubquiz", "Biodanza voorstelling", "Open dag Volksdansgroep",
                  "Workshop schilderen voor beginners", "Concert voor 12,50", "Dark Sky weekend", "Stille tocht",
                  "Seniorentheater", "Herfstwandeling", "Concert verplaatst naar nieuwe datum", "Welkom bij de Kerstmarkt",
                  "Thema: Halloween griezeltocht", "// Live: Racoon", "Lezing werkgroep Oud Ezinge",
                  "Excursie werkgroep vogels", "Lezing: ChatGPT en AI", "50+ Party met DJ Henk", "Hitster avond voor 5,00",
                  "Nijjierstoernooi en -resepsje VV Suameer", "Educa Symfonia – Open Repetitie", "Openbare repetitie NNO", "Open generale repetitie"):
        assert not not_an_outing(_event(title)), title


def test_tijd_achter_de_naam_valt_weg():
    assert clean_title("BEEF 16:00 - 17:05") == "BEEF"
    assert clean_title("Victor Pãtrãşcan – Stand up Comedy in broken English I 20.00-21.30") == \
        "Victor Pãtrãşcan – Stand up Comedy in broken English"


def test_soort_bij_zalen_en_namen():
    def kind(title, url="https://dorp.example/agenda/x"):
        event = _event(title)
        event["url"] = url
        event["sources"] = [{"url": url, "host": url.split("/")[2]}]
        return classify(event, OVERRIDES)["kind"]
    assert kind("Long Legs Mosquito albumpresentatie") == "muziek"
    assert kind("Nina Bailey – EP Release") == "muziek"
    assert kind("Uurtje cultuurtje: de Molukse bewoners") == "lezing"
    assert kind("Bluegrass Boogiemen", "https://engelstede.nl/event/bluegrass-boogiemen/") == "muziek"
    assert kind("BEEF", "https://jongeharten.podiumnederland.nl/mtTicket/performance/1") == "theater"
    assert kind("Wat als niemand de baas is?", "https://forum.nl/nl/agenda/talks-events/wat-als") == "lezing"


def test_concerten_op_dezelfde_avond_in_een_grote_zaal_blijven_apart():
    """De Oosterpoort: 'RONDÉ – support: Melle' en een ander concert met support op dezelfde avond werden
    samengevoegd op het woord 'support' (vergelijking met VisitGroningen, oktober 2026)."""
    from pipeline.v2.convert import merge_same_venue
    def ev(title, url):
        return {"title": title, "url": url, "venue": {"name": "De Oosterpoort", "city": "Groningen"},
                "occurrences": [{"date": "2026-11-20", "startTime": "20:00"}], "sources": [{"url": url}], "tags": []}
    out = merge_same_venue([ev("RONDÉ – support: Melle", "https://s.nl/a"), ev("Pitou – + support: FEMI", "https://s.nl/b"),
                            ev("Noord Nederlands Orkest – Anime in Concert", "https://s.nl/c"),
                            ev("Nederlands Blazers Ensemble", "https://s.nl/d")])
    assert len(out) == 4
    same = merge_same_venue([ev("HAEVN", "https://s.nl/e"), ev("HAEVN – + support: Ilse", "https://t.nl/e")])
    assert len(same) == 1
    # De naam van de plek telt niet als gedeeld woord ('Drents-Friese Wold').
    def wold(title, url):
        e = ev(title, url)
        e["venue"] = {"name": "Drents-Friese Wold", "city": "Appelscha"}
        return e
    assert len(merge_same_venue([wold("Workshop natuurjournalen Drents-Friese Wold", "https://n.nl/a"),
                                 wold("Roofvogel fietstocht in het Drents-Friese Wold", "https://n.nl/b")])) == 2


def test_cabaret_met_striptease_in_de_naam_is_geen_stripshow():
    assert not not_an_outing(_event("David Linszen – Striptease Van De Dood"))
    for title in ("Striptease show met strippers", "Male striptease", "Striptease-avond", "Ladies night striptease"):
        assert not_an_outing(_event(title)), title


def test_praktische_zaken_gaan_uit_een_lange_naam():
    # Datum, aanvang, zaal open, leeftijd, plaats en gebouw staan al bij het uitje (Fever-vergelijking, 21 oktober 2026).
    assert clean_title("LBE – Dido & Aeneas – Groningen– Martinikerk – 22 oktober 2026 – aanvang 19.30 uur – jongeren "
                       "t/m 27 jaar – zaal open 30 minuten voor aanvang concert", "Groningen", "Martinikerk I Groningen") \
        == "LBE – Dido & Aeneas"
    assert clean_title("Live: The Acoustic Roos — BROUWDOK BUITENDIJKS", "Harlingen", "Brouwdok Buitendijks") \
        == "Live: The Acoustic Roos"
    assert clean_title("UITfestival SWF | Sneek", "Sneek", None) == "UITfestival SWF"
    assert clean_title("Film avond – 29 oktober") == "Film avond"
    assert clean_title("Nacht van de Nacht van 19.30 – ca. 21.00 uur. Verzamelen bij de kerk van Eenum.") == "Nacht van de Nacht"
    assert clean_title("Japanse Theeproeverij *WEGENS SUCCES VOLGEBOEKT*") == "Japanse Theeproeverij"
    assert clean_title("Activiteit Concert van NIHZ") == "Concert van NIHZ"
    assert clean_title("Expositie Zij hielden koers 7 november 2026 t/m 17 mei 2027") == "Expositie Zij hielden koers"
    # De echte naam blijft heel: artiest en voorstelling, of een plaats die de naam is.
    for title in ("Noord Nederlands Orkest en Alexei Volodin – Rachmaninoff Paganini-rapsodie",
                  "Ghostbusters Halloween Experience – SPOT | X YUSUF BOSS | De Wijk De Wereld",
                  "Groningen – Stad van verhalen", "Expositie 7 november", "Sneek – Sneekweek"):
        assert clean_title(title, "Sneek", "Theater Sneek") == title, title
    assert clean_title("Explore the North Festivalweekend vr 20 – zo 22 nov") == "Explore the North Festivalweekend"


def test_inkorten_laat_de_echte_naam_heel():
    # Nakijkronde: alleen het gebouw valt weg, geen deel van de naam; nooit één los woord over; kaartsoort weg.
    assert clean_title("Bach – Groningen – Johannes Passion – 2 april", "Groningen", "Martinikerk") == "Bach – Johannes Passion"
    assert clean_title("Muziek | De Oosterpoort", "Groningen", "De Oosterpoort") == "Muziek | De Oosterpoort"
    assert clean_title("LBE – Messiah – reguliere ticket", "Groningen", "Martinikerk") == "LBE – Messiah"
    assert clean_title("LBE – Matthäus Passion – Antwerpen – Sint-Carolus Borromeuskerk – 9 maart 2027", "Antwerkpen",
                       "Sint-Carolus Borromeuskerk / Antwerpen") == "LBE – Matthäus Passion"
    assert clean_title("Zomervakantie rijlessen Zomervakantie rijlessen 20 juli t/m 16 augustus 2026") == "Zomervakantie rijlessen"


def test_datums_in_fries_en_met_de_maand_eerst():
    # Dorpsapp.nl (gauw.frl, ijlst.frl) en beurzen van WTC Expo (Drenthe/Friesland-ronde, 22 oktober 2026).
    from datetime import date
    from collector.when import parse_end_day, parse_when
    today = date(2026, 10, 22)
    assert parse_when("okt. 28", today=today) == "2026-10-28"
    assert parse_when("des. 5 19:30", today=today) == "2026-12-05T19:30"
    assert parse_when("12 desimber 2026", today=today) == "2026-12-12"
    assert parse_when("april 12:00", today=today) is None
    assert parse_end_day("13-11-2026 t/m 14-11-2026", "2026-11-13") == "2026-11-14"
    assert parse_end_day("13-11-2026", "2026-11-13") is None
