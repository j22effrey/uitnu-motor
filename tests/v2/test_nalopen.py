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
                  "Workshop: Cyberveiligheid in begrijpelijke taal", "Pubquiz 50+",
                  "Anders vieren dienst m.m.v. Rokus Maasland/ The Bowery"):
        assert not_an_outing(_event(title)), title


def test_echte_uitjes_blijven_staan():
    for title in ("Natuurwerkdag Buningshof", "Jeugdworkshop Vogelkastjes timmeren Buningshof", "Concerten in de kerk",
                  "Sinterklaasintocht Meeden", "Pubquiz", "Biodanza voorstelling", "Open dag Volksdansgroep",
                  "Workshop schilderen voor beginners", "Concert voor 12,50", "Dark Sky weekend", "Stille tocht",
                  "Seniorentheater", "Herfstwandeling", "Concert verplaatst naar nieuwe datum", "Welkom bij de Kerstmarkt",
                  "Thema: Halloween griezeltocht", "// Live: Racoon", "Lezing werkgroep Oud Ezinge",
                  "Excursie werkgroep vogels", "Lezing: ChatGPT en AI", "50+ Party met DJ Henk", "Hitster avond voor 5,00",
                  "Nijjierstoernooi en -resepsje VV Suameer"):
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
