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
    assert clean_title("Zomerconcert in het park vanaf 5 mei") == "Zomerconcert in het park vanaf 5 mei"


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


def test_maand_eerst_alleen_als_datum_aan_het_begin():
    # Nakijkronde: 'vanaf maart 2 x per week' of 'mei 5 km loop' is geen datum.
    from datetime import date
    from collector.when import parse_when
    today = date(2026, 10, 27)
    for text in ("vanaf maart 2 x per week", "mei 5 km loop", "Fête des 3 rois", "jun 30 jaar jubileum"):
        assert parse_when(text, today=today) is None, text
    assert parse_when("za okt. 31", today=today) == "2026-10-31"


def test_kerkdiensten_huwelijken_en_kaatsmuseum():
    from pipeline.v2.classify import not_an_outing
    for title in ("Huwelijk", "Kerkzangdienst", "Advent viering", "Reformatie zondag", "Kerstnachtviering"):
        assert not_an_outing(_event(title)), title
    assert not not_an_outing(_event("Adventsconcert met koor"))


def test_soortenronde_oktober_2026():
    # Volledige ronde over alle soorten (27 oktober 2026): algemene regels, met uitzonderingen voor echte uitjes.
    from pipeline.v2.classify import classify
    kind = lambda title: classify({"title": title})["kind"]
    assert kind("Tennis op gravelbaan Nes") == "sport"
    assert kind("Woezel & Pip De Musical – Feest in de Tovertuin (2+)") == "kinderen"
    assert kind("De grote Sinterklaasshow") == "kinderen"
    assert kind("Intocht Sinterklaas") == "feest"
    assert kind("Krezip – Theatertour") == "muziek"
    assert kind("Nirvana Unplugged") == "muziek"
    assert kind("Sunday Jam") == "muziek"
    assert kind("De Misdaadpodcast Live") == "lezing"
    assert kind("Topstukken Klassieke Muziek: Mahler") == "lezing"
    assert kind("Daddy Cool in De Koornbeurs") != "markt"
    assert kind("Docs: Cutting Through Rocks") == "film"
    assert kind("Zitmaaierrace Ureterp") == "sport"
    assert kind("Amazing Grace") != "sport"
    assert kind("90-jarig jubileum CSVO") == "feest"
    assert kind("Jandino – De grote jubileumshow") != "feest"
    assert kind("Kerstworkshop op een houten schaats") == "lezing"
    for title in ("Fiering fanút de Martini tsjerke", "2de Advent", "Gedachteniszondag", "Viering vanuit de Martini kerk Easterein"):
        assert not_an_outing(_event(title)), title
    # Nakijkronde: echte uitjes met dezelfde woorden blijven staan.
    for title in ("Adventsconcert in de Martinikerk", "Concert 4e advent Martinikerk", "3e Advent: kerstconcert met kamerkoor",
                  "Viering vanuit de Martinikerk: Bach cantate", "Feestelijke fiering 100 jaar kaatsclub", "Fiering fan Sinteklaas",
                  "Matthäus Passion 40 dagen tiid", "Scoor je tickets voor Avondvibes"):
        assert not not_an_outing(_event(title)), title
    assert kind("Playbackshow Kollum") != "lezing"
    assert kind("Jam maken met de kinderen") != "muziek"
    assert kind("Tarot reading") != "lezing"
    assert kind("Celtic Steps – An Irish Christmas") == "theater"
    assert kind("Kerstcarols bij de boom") == "muziek"
    assert classify({"title": "Najib Amhali – Theatertour", "schemaType": "ComedyEvent"})["kind"] == "theater"


def test_grensregister_mag_verder_over_de_grens():
    # De Gallimarkt in Leer (ongeveer 20 km over de grens) alleen als hij in het grensregister staat.
    from pipeline.v2.build import in_area
    leer = {"venue": {"lat": 53.2316, "lon": 7.4446}}
    assert not in_area(leer)
    assert in_area({**leer, "grensUitje": True})
    assert not in_area({"venue": {"lat": 53.0793, "lon": 8.8017}, "grensUitje": True})   # Bremen: te ver


def test_een_bron_die_ineens_leeg_is_houdt_de_agenda_niet_tegen():
    # Oktober 2026: Parkzicht en VVV Ameland leverden ineens niets; de keuring hield vier rondes alles tegen.
    from collections import Counter
    from pipeline.v2.gate import dropped_hosts
    old = [{"id": f"p{i}", "sources": [{"host": "parkzicht.com"}], "occurrences": [{"date": "2026-11-01"}]} for i in range(12)]
    assert dropped_hosts([], old, "2026-10-27", delivered=Counter()) == ["parkzicht.com"]
    assert dropped_hosts([], old, "2026-10-27", retired_hosts={"parkzicht.com"}, delivered=Counter()) == []


def test_dagcontrole_27_oktober_hulp_spelavond_en_discussieavond():
    # Hulp met telefoon of computer, een bordspelavond in het dorp en een discussieavond zijn geen uitje.
    for title in ("Walk-in Smartlab", "Bordspelavond", "Bordspelavond voor jong en oud, schuif gezellig aan!",
                  "Discussieavond 3 november over Hoe het gaat met de jeugd"):
        assert not_an_outing(_event(title)), title
    # Echte uitjes met dezelfde woorden blijven staan.
    for title in ("Bordspellentoernooi Groningen", "Bieb Vibes: Bordspellencafé", "Hitster avond voor 5,00",
                  "Walk-in concert in de Martinikerk", "Walk-in Workshop keramiek", "Walk-in Disco",
                  "Debat: discussieavond met de lijsttrekkers live", "Bordspelavond met live muziek"):
        assert not not_an_outing(_event(title)), title


def test_dagcontrole_1_november_mededelingen_cursus_en_gebed():
    for title in ("Omrin november", "Agenda 12 november 2026", "Nederlands Nog 18 plekken vrij", "Nederlands Volgeboekt",
                  "English Nog 1 plek vrij", "Bidden voor Vrede", "Ontmoetingsochtenden MFC"):
        assert not_an_outing(_event(title)), title
    for title in ("Agenda 12 november: Kerstmarkt", "Bidden voor vrede: concert in de Martinikerk",
                  "Workshop Nederlands nog 3 plekken vrij", "Pubquiz - nog 3 plekken vrij",
                  "Kinderdisco - nog 10 plekken vrij", "Rondleiding Planetarium - nog 4 plaatsen vrij", "Omrin duurzaamheidsfestival", "Ontmoetingsavond met de schrijver: lezing"):
        assert not not_an_outing(_event(title)), title


def test_dagcontrole_1_november_jeugdwedstrijd_met_plusje():
    assert not_an_outing(_event("Tzummarum 18+1 - Zeerobben 18+1"))
    page = {**_event("Thuisploeg - Uitploeg"), "url": "https://www.scfraneker.nl/200/63638/uitslagen/wedstrijd-details/"}
    assert not_an_outing(page)
    assert not not_an_outing(_event("Boney M 1976 - Het feest"))
    assert not not_an_outing({**page, "title": "Zaalvoetbaltoernooi"})


def test_dagcontrole_1_november_rommel_in_de_naam():
    junk = 'Other Mommy (16 jr.), dinsdag 3 november 21:20"> Bestel @keyframes fadeIn { from { opacity: 0; } }'
    assert clean_title(junk) == "Other Mommy (16 jr.)"
    assert clean_title('Vier minus drei, maandag 16 november 13:00"> Bestel') == "Vier minus drei"
    assert clean_title("Wine > Beer") == "Wine > Beer"
    assert clean_title('Concert "Bach 300" > uitverkocht') == 'Concert "Bach 300" > uitverkocht'


def test_dagcontrole_1_november_soorten():
    def kind(title, url="https://dorp.example/agenda/x"):
        event = {**_event(title), "url": url, "sources": [{"url": url, "host": url.split("/")[2]}]}
        return classify(event, OVERRIDES)["kind"]
    assert kind("Pop-up Museum 20 jaar paardenredding") != "muziek"
    assert kind("Pop-up concert") == "muziek"
    assert kind("Stroomdalkapel geeft concert in Eetcafé Hoving") == "muziek"
    assert kind("Eetcafé De Poort") == "eten"
    assert kind("Leren boekbinden") == "lezing"
    assert classify({"title": "Het Diner", "url": "https://denieuwekolk.nl/bios/agenda/het-diner"})["kind"] == "film"


def test_dagcontrole_1_november_rondleiding_in_inschrijfformulier():
    """Slavernijverleden Groningen: de rondleiding staat alleen als keuzes in het formulier (titleText)."""
    from datetime import date
    from collector import html_cards
    html = ('<span class="event-choice"><span class="day">Zaterdag</span><span class="date">7</span>'
            '<span class="month">november</span><span class="time">10:00 - 12:00</span>'
            '<span class="event-language">Nederlands</span><span class="places">Nog 1 plek vrij</span></span>'
            '<span class="event-choice"><span class="day">Zaterdag</span><span class="date">3</span>'
            '<span class="month">april</span><span class="time">10:00 - 12:00</span>'
            '<span class="event-language">English</span><span class="places">Nog 25 plekken vrij</span></span>')
    cfg = {"card": '<span class="event-choice', "titleText": "Stadswandeling Slavernijverleden Groningen",
           "fields": {"date": 'class="date">(\\d{1,2}</span>\\s*<span class="month">[a-z]+)<',
                      "time": 'class="time">\\s*(\\d{1,2}[:.]\\d{2})', "end": 'class="time">[^<]*?-\\s*(\\d{1,2}[:.]\\d{2})',
                      "extra": 'class="event-language">([^<]+)<'},
           "skipExtra": "^Nederlands$"}
    events = html_cards.parse_cards(html, cfg, source_name="S", page_url="https://s.example/", today=date(2026, 11, 2))
    assert [(e.title, e.start_at, e.end_at) for e in events] == [
        ("Stadswandeling Slavernijverleden Groningen", "2026-11-07T10:00", "2026-11-07T12:00"),
        ("Stadswandeling Slavernijverleden Groningen – English", "2027-04-03T10:00", "2027-04-03T12:00")]


# Dagcontrole 2 november 2026 (252 nieuwe uitjes): wat er nog tussen zat.
def test_dagcontrole_2_november_geen_uitje():
    for title in ("Stampot eten in het Bartoleshûs", "Koppelkaarten in Dorpshuis de Molenwiek", "Mini-klup kampioenskip",
                  "Bijeenkomst Verbinding zondag 22 november", "Bijeenkomst Feilich Ûnderweis",
                  "Uitnodiging Plekberaad De Lege Geaën", "Gezamenlijke klimaatdienst",
                  "Parochiebrede Avond", "Droge worst aktie VVR", "Drop aktie VVR ⚽", "ophalen schoentje in het Heirhuys.",
                  "Acteercursus", "Moi-cursus", "Djembe met Ria Ybema",
                  "2026 Volgend jaar Oktober 2026 Zaterdag, 31 Oktober 2026", "Foar yn de agenda", "Film in Friesland", "bijeenkomst 1", "bijeenkomst 4 (afsluiting)"):
        assert not_an_outing(_event(title)), title


def test_dagcontrole_2_november_echte_uitjes_blijven_staan():
    for title in ("Acteercursus-openbare les", "Stampot buffet met live muziek", "Bijeenkomst en lezing over Menno ter Braak",
                  "Kerstconcert 'Keep the Faith'", "Workshop bloembollen planten",
                  "Cursus Fotografie met Smartphone", "Ophalen prins carnaval", "Bijeenkomst Open Dag", "Bijeenkomst Dichters in de Kerk",
                  "Bijeenkomst Poëzie en muziek", "Bijeenkomst Kerstfair", "Film in Friesland: Brimstone", "Pubquiz VVR", "Klaverjasdrive voor iedereen: prijsklaverjassen"):
        assert not not_an_outing(_event(title)), title


def test_een_ligconcert_is_muziek():
    assert classify(_event("Een ligconcert met Yoga Nidra & Neoklassieke klanken van piano en bugel"))["kind"] == "muziek"
    assert classify(_event("Yoga in het park"))["kind"] == "sport"


def test_afgebroken_naam_valt_weg():
    assert clean_title("Kerstconcert 'Keep the Faith'-…") == "Kerstconcert 'Keep the Faith'"
    assert clean_title("Kerstconcert 'Keep the Faith'…") == "Kerstconcert 'Keep the Faith'"
    # het soortlabel achter de naam blijft: het is bewijs voor de soort (Le ballon rouge | Klassieke muziek)
    assert clean_title("Le ballon rouge | Klassieke muziek") == "Le ballon rouge | Klassieke muziek"


def test_bronnen_van_het_onderhoud_van_2_november_staan_goed_ingesteld():
    """EM2 (kaartjeslijst in plaats van gegevens in de pagina) en de thuiswedstrijden van FC Groningen."""
    sources = {s["id"]: s for s in json.loads((Path(__file__).parents[2] / "collector" / "web_crawl_sources.json")
                                              .read_text(encoding="utf-8"))["sources"]}
    em2, fcg = sources["em2groningen-nl-web"], sources["fcgroningen-nl-thuiswedstrijden"]
    assert em2["extractorHint"] == "html_cards" and em2["defaultPlace"]["venue"] == "EM2"
    assert fcg["extractorHint"] == "html_cards" and fcg["kindHint"] == "sport"
    # uitwedstrijden (links een andere ploeg) worden overgeslagen, thuiswedstrijden niet
    import re
    skip = re.compile(fcg["extractorConfig"]["skipTitle"], re.I)
    assert skip.search("AZ – FC Groningen") and not skip.search("FC Groningen – PSV")


# Dagcontrole 3 november 2026 (412 nieuwe uitjes): kopjes van websites, nieuwsberichten, dankdag.
def _news(title, path):
    event = _event(title)
    event["url"] = f"https://dorp.example{path}"
    return event


def test_dagcontrole_3_november_geen_uitje():
    for title in ("Bericht navigatie", "Berichten paginering", "Starts at 11:00", "Events", "Evenementen in en om Rolde",
                  "Het weer in Rolde", "Ophaaldagen in Rolde", "Dankdagviering", "Stemmen op Dorpshuis v/h jaar",
                  "Uitzending op RTV Drenthe"):
        assert not_an_outing(_event(title)), title
    assert not_an_outing(_news("Kledingbieb krijgt vaste plek boven Blij van Toen", "/nieuws/kledingbieb-krijgt-vaste-plek"))
    assert not_an_outing(_news("Levendig Musselkanaal als snelkoppeling op je telefoon!", "/berichten/levendig-musselkanaal"))
    assert not_an_outing(_news("Beste dorpsbewoners,", "/author/garsthuizen/"))


def test_dagcontrole_3_november_echte_uitjes_blijven_staan():
    for title in ("Events Night met live muziek", "Evenementen in en om Rolde: de Kerstmarkt", "Dankdagconcert in de kerk", "Dankdagviering met orgelconcert"):
        assert not not_an_outing(_event(title)), title
    for title, path in (("Workshop Kerstballen schilderen à la Van Gogh", "/nieuws/kerstballen-schilderen"),
                        ("Bierproeverij", "/author/garsthuizen/"), ("Spooktocht Zeerijp", "/author/garsthuizen/"),
                        ("Lezing: Het verzet door de familie Brouwer tijdens WOII", "/nieuws/"),
                        ("20 november Bingojûn met Fegebart – live muziekbingo", "/home/nieuws/17-cultuur/2076")):
        assert not not_an_outing(_news(title, path)), title


def test_festivalhart_pannenkoek_en_microscopiedag_krijgen_de_goede_soort():
    for title, kind in (("FESTIVALHART DAG 3", "theater"), ("FESTIVALHART DAG 5", "theater"),
                        ("Theater Pannenkoek - Kom uit die kraan!", "kinderen"), ("Microscopiedag in Groningen en Drenthe", "lezing")):
        assert classify(_event(title), OVERRIDES)["kind"] == kind, title


# Dagcontrole 4 november 2026 (274 nieuwe uitjes): kopjes, mededelingen, dorpsroutines, datum achter de naam, soorten.
def test_dagcontrole_4_november_geen_uitje():
    for title in ("AKTIVITEITEN KALENDER 2026", "Activiteitenkalender", "Wedstrijdschema SC Angelslo 1",
                  "5 5 november 2026 ● (1 evenement) Internationaal Race Event PNWC 5",
                  "Opendeurdienst", "Christus, Koning van het heelal", "Verkiezingsweek waterschap/ provinciale",
                  "De kaartferkeap fan it Mearke 2026 is los!", "Kerstboom plaatsen", "Test concert in the Jacobuskerk",
                  "Koffie-ochtend", "Koffie en spelletjes", "Eten is ontmoeten", "Schuif eens gezellig aan", "Vrouwenavond"):
        assert not_an_outing(_event(title)), title


def test_dagcontrole_4_november_echte_uitjes_blijven_staan():
    for title in ("Koffieconcert met het Noorder Kamerkoor", "Verkiezingsdebat met de lijsttrekkers", "Kaartverkoop live optreden gestart: voorstelling",
                  "Test Match: Nederland - Duitsland", "Wedstrijd Kaatsen Franeker",
                  "Wildavond met live muziek", "Efteling vertelt... Baron 1898", "Wacht even... het concert begint",
                  "Advendo BBD presenteert: Disney in Conc... zondag 15 november 2026", "Verkiezingsavond met live muziek"):
        assert not not_an_outing(_event(title)), title


def test_datum_achter_de_naam_valt_weg_maar_een_periode_blijft_heel():
    assert clean_title("Bier, kluif en ballen 28 november 2026") == "Bier, kluif en ballen"
    assert clean_title("Kerstconcert Excelsior Schraard op 13 december") == "Kerstconcert Excelsior Schraard"
    assert clean_title("Expositie Zij hielden koers 7 november 2026 t/m 17 mei 2027") == "Expositie Zij hielden koers"
    assert clean_title("Explore the North Festivalweekend vr 20 – zo 22 nov") == "Explore the North Festivalweekend"
    assert clean_title("Zomerconcert in het park vanaf 5 mei") == "Zomerconcert in het park vanaf 5 mei"


def test_giethoorn_forum_soorten():
    for title, kind in (("Wildavond", "eten"), ("Local Wild: game from De Wieden", "eten"), ("Onbeperkt spareribs weekend", "eten"),
                        ("DomoticaGrunn", "lezing"), ("Kleintje Koffie 2027 (0+)", "kinderen")):
        assert classify(_event(title), OVERRIDES)["kind"] == kind, title


# Dagcontrole 5 november 2026 (122 nieuwe uitjes): werkgroepen, yogalessen, reispakketten, verenigingsnaam, plusje.
def test_dagcontrole_5_november_geen_uitje():
    for title in ("Vogelwerkgroep", "Plantenwerkgroep", "Keatsferiening", "Nieuw blok yogalessen start 21 oktober de kaats kantine",
                  "5-day Music Spectacle", "4-Daagse muziekreis met Dana Winner"):
        assert not_an_outing(_event(title)), title


def test_dagcontrole_5_november_echte_uitjes_blijven_staan():
    for title in ("Lezing werkgroep Oud Ezinge", "Yoga workshop in het park", "Yoga festival", "Jubileum vereniging: concert",
                  "Reis door de tijd: voorstelling", "3-daagse Kerstmarkt", "Excursie vogelwerkgroep Zuidwolde", "Natuurwerkgroep Rondleiding"):
        assert not not_an_outing(_event(title)), title


def test_plusje_voor_de_naam_valt_weg_en_soorten():
    assert clean_title("+ Annemarijn Maandag") == "Annemarijn Maandag"
    assert clean_title("A+B Festival") == "A+B Festival"
    for title, kind in (("Kom maar, kipjes! | Kippenpret", "kinderen"), ("Top 2000 Krystkafee", "feest")):
        assert classify(_event(title), OVERRIDES)["kind"] == kind, title


# Dagcontrole 6 november 2026 (111 nieuwe uitjes): kapotte dubbele link, vrijwilligersdag, dorpshuisroutines.
def test_dubbele_website_voor_de_link_wordt_hersteld():
    from pipeline.v2.convert import _web_link
    assert _web_link("https://www.greetsiel.dehttps://www.greetsiel.de/erlebnisse/veranstaltungskalender") == \
        "https://www.greetsiel.de/erlebnisse/veranstaltungskalender"
    assert _web_link("https://www.landesmuseum-emden.de/veranstaltungenhttps://www.landesmuseum-emden.de/veranstaltungen") == \
        "https://www.landesmuseum-emden.de/veranstaltungen"
    assert _web_link("https://www.landesmuseum-emden.dehttps://www.landesmuseum-emden.de/veranstaltungenhttps://www.landesmuseum-emden.de/veranstaltungen") == \
        "https://www.landesmuseum-emden.de/veranstaltungen"
    assert _web_link("https://a.de/x/https://a.de.example") == "https://a.de/x/https://a.de.example"
    assert _web_link("https://dorp.example/agenda/x?url=https://elders.example/") == "https://dorp.example/agenda/x?url=https://elders.example/"


def test_dagcontrole_6_november_geen_uitje():
    for title in ("SW Doet", "NL Doet", "DorpsStee", "Thuiskamer", "Thuiskeuken",
                  "H'Andel Winkel", "Ontmoet elkaar in de Ontmoeting"):
        assert not_an_outing(_event(title)), title


def test_dagcontrole_6_november_echte_uitjes_blijven_staan():
    for title in ("Weihnachtsmarkt in Visquard", "Kerstmarkt Hooghalen", "Boerenmarkt met live muziek", "Thuiskeuken workshop: sushi maken",
                  "DorpsStee Kerstconcert", "Wochenmarkt in Pewsum"):
        assert not not_an_outing(_event(title)), title


def test_herstelde_link_is_geen_lege_bron():
    # 6 november 2026: de dagcontrole herstelde 'https://www.greetsiel.dehttps://www.greetsiel.de/...'. Het webadres van
    # die uitjes werd 'greetsiel.de' in plaats van 'greetsiel.dehttps:'; de keuring zag de oude naam als lege bron en
    # hield twee rondes alles tegen. Staan de uitjes er nog (zelfde id of adres), dan is de bron niet leeg.
    from collections import Counter
    from pipeline.v2.build import carry_over
    from pipeline.v2.gate import dropped_hosts, run_gate

    def event(i, host, title=None):
        return {"id": f"{host}{i}", "slug": f"{host}-{i}", "title": title or f"Uitje {i}", "kind": "markt",
                "url": f"https://{host}/agenda/{i}", "occurrences": [{"date": "2026-11-20"}],
                "venue": {"city": "Greetsiel"}, "sources": [{"host": host, "url": f"https://{host}/agenda/{i}"}]}
    renamed = [{**event(i, "greetsiel.dehttps:"), "id": f"g{i}", "slug": f"greetsiel-{i}"} for i in range(12)]
    empty = [event(i, "podium.example", f"Concert {i}") for i in range(12)]
    matches = [event(i, "club.example", f"Club JO1{i}-1 - Gasten JO1{i}-2") for i in range(12)]
    previous = renamed + empty + matches
    new = [{**event(i, "greetsiel.de"), "id": f"g{i}", "slug": f"greetsiel-{i}"} for i in range(12)]
    delivered = Counter({"greetsiel.de": 12})
    dropped = dropped_hosts(new, previous, "2026-11-06", delivered=delivered)
    assert sorted(dropped) == ["club.example", "greetsiel.dehttps:", "podium.example"]
    before = {c["name"]: c["passed"] for c in run_gate(new, previous, "2026-11-06", delivered=delivered)["checks"]}
    assert before["geen_bron_ineens_leeg"] is False

    carried, covered, ruled_out, delivered = carry_over(new, previous, dropped, "2026-11-06", delivered)
    # De hernoemde bron staat er nog; de echt lege bron houdt zijn uitjes van de vorige keer (zoals eerder);
    # de jeugdwedstrijden van een club gaan door de regels van nu en blijven niet staan (vaste regel 4).
    assert covered == {"greetsiel.dehttps:": 12}
    assert carried == {"podium.example": 12}
    assert ruled_out == {"club.example": 12}
    assert len(new) == 24 and not any("JO1" in e["title"] for e in new)
    checks = {c["name"]: c["passed"] for c in run_gate(new, previous, "2026-11-06", delivered=delivered)["checks"]}
    assert checks["geen_bron_ineens_leeg"]

    # Een wedstrijd op de sites van beide clubs telt voor allebei.
    both = {**matches[0], "id": "x", "slug": "x", "sources": [{"host": "club.example"}, {"host": "andere.example"}]}
    _, _, ruled_out, _ = carry_over([], [both], ["club.example", "andere.example"], "2026-11-06", Counter())
    assert ruled_out == {"club.example": 1, "andere.example": 1}


# Dagcontrole 7 november 2026 (115 nieuwe uitjes): clubprogramma's, rummiclub, scootmobieltraining, huisbezoek.
def test_dagcontrole_7_november_geen_uitje():
    for title in ("Programma thuis", "Selecties zaterdag", "Matchday", "VVS O11-1JM", "Museum open in 2027", "Klaver-rummiclub",
                  "Scootmobieltraining Zuidhorn", "Groot huisbezoek Hijken-Hooghalen"):
        assert not_an_outing(_event(title)), title


def test_dagcontrole_7_november_echte_uitjes_blijven_staan():
    for title in ("Museum open in 2027: nieuwe expositie", "Rummikub toernooi voor iedereen", "Matchday live: concert na afloop",
                  "Programma thuis in Concert", "Klaver-rummiclub toernooi", "Selecties zaterdag: open dag",
                  "Huisbezoek van Sinterklaas", "Scootmobieltocht Westerkwartier", "Scootmobielrally", "Mo1-2", "Jazz J5-3", "M83-1"):
        assert not not_an_outing(_event(title)), title


def test_lets_gro_buiten_het_gebouw():
    # 6 november 2026: de silent disco in de Haddingestraatgarage (Let's Gro, van Forum) ontbrak. Forum's eigen agenda
    # leest alleen het gebouw; het programma op andere plekken staat op een eigen pagina, met de plek per uitje.
    import json
    from datetime import date
    from pathlib import Path
    from collector import html_cards
    from collector.active_source_runner import apply_default_place, default_place
    sources = json.loads((Path(__file__).parents[2] / "collector" / "web_crawl_sources.json").read_text(encoding="utf-8"))
    source = next(s for s in sources["sources"] if s["id"] == "forum-nl-letsgro")
    item = ('<li>\n <a href=""\n data-id="{id}"\n data-date="06-11-2026"\n data-start="11/06/2026 19:00"\n'
            ' data-end="11/06/2026 21:00"\n data-location="{loc}"\n data-ticket-title="Meer info"\n'
            ' data-ticket-link="https://forum.nl/nl/agenda/talks-events/{slug}">\n <img src="x.jpg" alt="{t}" />\n'
            ' <span class="title">{t}</span>\n <span class="text"><p>Tekst</p></span>\n </a>\n</li>')
    page = "<ul>" + item.format(id=1645768, loc="Haddingestraatgarage", slug="silent-disco-in-de-haddingestraatgarage",
                                t="Silent disco in de Haddingestraatgarage") \
        + item.format(id=1, loc="Externe Locaties", slug="mensa", t="Mensa") + "</ul>"
    events = html_cards.parse_cards(page, source["extractorConfig"], source_name=source["name"],
                                    page_url=source["extractorConfig"]["endpointUrl"], today=date(2026, 11, 6))
    [disco] = [apply_default_place(e, default_place(source)) for e in events]   # samen eten (Mensa) valt weg
    assert disco.title == "Silent disco in de Haddingestraatgarage"
    assert disco.start_at.startswith("2026-11-06T19:00") and disco.end_at.startswith("2026-11-06T21:00")
    assert (disco.venue, disco.city, disco.lat) == ("Haddingestraatgarage", "Groningen", None)
    assert disco.source_url == "https://forum.nl/nl/agenda/talks-events/silent-disco-in-de-haddingestraatgarage"


def test_festivalpagina_die_weg_is_is_leeg():
    # Tussen twee edities van Let's Gro kan Forum de pagina weghalen (404). Met missingIsEmpty is de bron dan leeg en
    # klaar; anders telt hij als storing en blijven alle uitjes van forum.nl van de vorige keer staan.
    from datetime import date
    from urllib.error import HTTPError
    import pytest
    from collector import html_cards
    from collector.site_crawler import Fetched

    def fetch(url, timeout=15):
        if url.endswith("robots.txt"):
            return Fetched(url=url, status=200, content_type="text/plain", text="User-agent: *\nDisallow: /views/\n")
        raise HTTPError(url, 404, "Not Found", {}, None)
    config = {"endpointUrl": "https://forum.example/nl/lets-gro-timetable", "card": "<li>", "fields": {"title": "<b>(.*?)</b>"}}
    with pytest.raises(HTTPError):
        html_cards.fetch(config, source_name="f", root_url="https://forum.example/", page_fetch=fetch, today=date(2027, 1, 5))
    assert html_cards.fetch({**config, "missingIsEmpty": True}, source_name="f", root_url="https://forum.example/",
                            page_fetch=fetch, today=date(2027, 1, 5)) == []


# Dagcontrole 8 november 2026 (123 nieuwe uitjes): kopjes, dorpsroutines, Frans/Frysk concert, clubbron uit.
def test_dagcontrole_8_november_geen_uitje():
    for title in ("Voorpagina", "De Bonte Wever 25", "Zondag 8 november 14:30 uur", "Zaterdag 21 november",
                  "Damensauna im Koppke Greetsiel", "Gratis verwendag voor minima", "Dorphuis open", "Zaterdag snack dag in Elim!"):
        assert not_an_outing(_event(title)), title


def test_dagcontrole_8_november_echte_uitjes_blijven_staan():
    for title in ("Zaterdag 21 november: Kerstmarkt", "Zondag 8 november Concert in de kerk", "Sauna-avond met live muziek",
                  "Dorpshuis open dag met optreden", "Voorpagina Festival", "Snackdag Foodtruck Festival"):
        assert not not_an_outing(_event(title)), title


def test_frysk_konsert_is_muziek():
    assert classify(_event("Hjerstkonsert Concordia de Gaastmar"), OVERRIDES)["kind"] == "muziek"
    assert classify(_event("Hjerstkonsert Concordia de Gaastmar + Pubkwis"), OVERRIDES)["kind"] == "muziek"


# Dagcontrole 9 november 2026 (57 nieuwe uitjes): kerkdiensten, klusdagen, Nederlandstalig reispakket, Führung.
def test_dagcontrole_9_november_geen_uitje():
    for title in ("1e advent, ds Peter Smilde Drachten", "Samenkomst", "Klusdagen Real80", "Klusdagen Offroad Real80",
                  "5-daags Muziekspektakel", "5-day Music Spectacle"):
        assert not_an_outing(_event(title)), title


def test_dagcontrole_9_november_echte_uitjes_blijven_staan():
    for title in ("Adventsconcert in de kerk", "Advent Markt", "Kerstmarkt Samenkomst op het plein", "Dagtrip naar Texel",
                  "Muziekspektakel in de Oosterpoort", "2-daags muziekspektakel", "3-daags Spektakel in Ahoy", "Rock ds Kapel", "Avond met ds Koos", "Mini ds fest", "Klusdag voor kinderen: workshop timmeren"):
        assert not not_an_outing(_event(title)), title


def test_fuhrung_in_het_museum_is_kunst():
    assert classify(_event("Öffentliche Führung durch die Sonderausstellung"), OVERRIDES)["kind"] == "kunst"
    assert classify(_event("Führung in plattdeutscher Sprache"), OVERRIDES)["kind"] == "kunst"
