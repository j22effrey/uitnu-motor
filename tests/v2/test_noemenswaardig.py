"""Alleen noemenswaardige uitjes (vraag van de eigenaar, 14 oktober: de dingen van Westerlee waren 'stuk
voor stuk niet noemenswaardig'). Wat een dorpshuis voor de eigen mensen doet, hulp en cursussen,
inspraak, mededelingen en het menu van een website gaan eruit; echte uitjes blijven staan."""
from datetime import date, timedelta

from collector.source_candidates import canonical_url
from pipeline.v2.build import routines
from pipeline.v2.classify import not_an_outing
from pipeline.v2.convert import clean_title, to_v2

TODAY = date(2026, 10, 14)


def _event(title):
    return {"title": title, "url": "https://dorp.example/agenda/x",
            "sources": [{"type": "organisator", "url": "https://dorp.example/agenda/x", "host": "dorp.example"}]}


def test_westerlee_niets_meer_van_de_vaste_dingen():
    for title in ("Klaverjassen", "Klaverjassen (kampioenschap v. teams)", "Bridge", "Fitness",
                  "Koffie ochtend Veur Mekoar", "Stut en Steun", "Westerlee 1 - SV Mussel 1"):
        assert not_an_outing(_event(title)), title


def test_vaste_ontmoetingen_in_het_dorp_zijn_niet_noemenswaardig():
    for title in ("Frietavond in het dorpshuis!", "Soepmaaltijd", "Op de koffie bij…", "Middag KoffieLeut", "Buurtbakje",
                  "Vrijdagmiddagborrel", "VrijMiBo", "Nieuwjaars borrel", "Kerstbrunch", "Winterbuffet", "Paaslunch",
                  "Doarpsmiel: samen koken, samen eten", "Duits Dorpsdiner", "Running Dinner: Nostalgisch Hellum",
                  "Dorpskamer: Koffie, stoelgymnastiek", "Doarpskeamer + Kledingreparatie", "Gezamenlijk eten in de Huiskamer",
                  "Handwerkcafé Stekje los", "Taalcafé", "Internetcafé", "Vrouwencafé", "Creatief café", "Hobbylub",
                  "Lekker Ite", "Bewegen en ontmoeten", "Snackavond", "Bakje Begine"):
        assert not_an_outing(_event(title)), title


def test_hulp_cursus_en_inspraak_zijn_niet_noemenswaardig():
    for title in ("Repair Café Oldeberkoop", "Mantelzorgcafé 2026", "Long Covid cafe", "Ik Sta Sterk – Valpreventie",
                  "AED cursus", "REANIMATIE CURSUS", "Opfrissen verkeersregels", "Werken met DigiD",
                  "Cursus: Orde op je Android", "Workshop veilige wachtwoorden", "2e werksessie Dorpsvisie",
                  "Woningbouw avond in Ons Gebouw", "Informatieavond torenspits kerk", "Inloopdag schade-energie-subsidies",
                  "Presentatie 1e conceptontwerp Dorpsplein", "Plaatselijk Belang – Ondernemersavond", "Nieuwjaarsreceptie",
                  "Open Lessen obs J. Emmens", "Filmmiddag groep 1-4", "Vriendendag", "Doarpsreünie Wynjewâld",
                  "Bloedprikken Certe", "Prikpost Certe", "Griepprik 2026", "Spreekuur wijkagent"):
        assert not_an_outing(_event(title)), title


def test_zorg_in_een_zaal_is_geen_uitje_maar_een_show_over_zorg_blijft():
    # 'Bloedprikken Certe' stond als theater in De Skans (19 oktober 2026)
    for title in ("Kapsalon de Musical", "Bloed, zweet en tranen – voorstelling"):
        assert not not_an_outing(_event(title)), title


def test_clubspel_competitie_en_mededelingen_zijn_geen_uitje():
    for title in ("Maatbiljarten Krekt Rekke", "Slottoenooi Krekt Rekke", "Slotdei bekerwedstrijd – Krijt op Tijd biljarten",
                  "Darten in Dorpshuis de Molenwiek", "Wintercompetitie tennis", "Sluitings- toernooi zaterdag 31 oktober",
                  "Covos MA1 – De Meeuwen MA1", "Friesland 1- SDS 1", "Herfstworkshop GAAT NIET DOOR!",
                  "GEEN frietavond in het dorpshuis", "VrijMiBo vervalt ivm Disco op 17 oktober", "Milieubus",
                  "Sortibak + grofvuil", "1 nov. a.s. uiterste inleverdatum voor de Praatmar", "Deadline Bronbankpraet",
                  "Provinciale Staten en Waterschapsverkiezingen", "Geef jouw beëindiging lidmaatschap door.",
                  "Wedstrijdoverzicht - week 42", "Rehabilitatie Duimstraat en Veenscheiding", "Kerstboomverkoop",
                  "Samenzangdienst God Unlimited", "Grunneger Dainst in Het Anker", "Dienst in het MFC – koffiedrinken",
                  "Kerstmiddag ouderen", "Jonge Kinderen 3-9, info volgt"):
        assert not_an_outing(_event(title)), title


def test_kerkdienst_onder_een_andere_naam_en_gebeden():
    for title in ("Ds. R. Sietsma", "Br. K. Braam", "Dienst met ds. Kuiper", "29e Zondag door het jaar", "2e advent",
                  "Dankdag", "Oudejaarsdienst", "Kerstavond", "Allerzielen 2026", "Taizegebed", "Avondgebed",
                  "Fryske Fesper", "Verdiepingskring over: Vrijheid", "Gedachtenisdienst", "Avondmaalsdienst"):
        assert not_an_outing(_event(title)), title
    # De rubriek in de link: een dienst onder de naam van de voorganger.
    assert not_an_outing({"title": "Arend Kroes", "url": "https://www.derank-groningen.nl/dienst/arend-kroes/"})
    assert not not_an_outing({"title": "Kerstconcert", "url": "https://kerk.example/vieringen/kerstconcert"})


def test_meditatie_ouderenclub_en_sportclub_zijn_geen_uitje():
    for title in ("Zondagochtend meditatie", "Weekend Vipassana meditatie", "Kerstretraite", "Deep Relaxation",
                  "55+ Actief Lutten - Prijzenbingo", "Café avond in Buurthuis", "Kantinediensten", "S.C. Erica 1",
                  "SC Erica 3 programma", "Aankomende diensten"):
        assert not_an_outing(_event(title)), title
    assert not_an_outing({"title": "Bingo in Buurthuis Vinkenbuurt.",
                          "url": "https://witharen.nl/activiteiten-en-verenigingen/welzijn-ouderen"})


def test_het_menu_van_een_website_is_geen_uitje():
    for title in ("Privacybeleid", "Filteren", "Je hebt het einde bereikt!", "Contact informatie", "Diensten menus",
                  "Educatie", "Specials", "1 t/m 12 van 76 resultaten", "October 2026", "January 2027", "Volgeboekt",
                  "Over deze voorstelling", "see our gallery", "Prikbord", "Aankomende gebeurtenissen", "A ctiviteiten",
                  "Event Type Activiteiten", "Uitslagen avond - Dorpsquiz", "Vandaag in de stad", "Evenementbeschrijving"):
        assert not_an_outing(_event(title)), title


def test_echte_uitjes_blijven_staan():
    for title in ("Koffieconcert Greidebrass", "Kom Erbij: Koffieochtend met cabaret", "Dorpskamer: Lezing Reitze Jonkman",
                  "Borrel met live muziek", "Theaterdiner", "Huiskamerconcert", "Huiskamerpodium Sleen en omgeving",
                  "Oliebollen Klaverjas Toernooi", "Klaverjastoernooi", "Bridgedrive", "Prijsklaverjassen", "Darttoernooi",
                  "Kerstmarkt basisschool De Kwinkslag", "Verlichte voertuigenoptocht (kinderen tot en met groep 8)",
                  "Workshop: mindfulness en positieve gezondheid", "Workshop vilten", "Pubquiz", "Muziekbingo met live band",
                  "Intocht Sinterklaas", "Nieuwjaarsduik", "Nieuwjaarsconcert", "Lunchconcert", "Plafonddienst – Plafonddienst",
                  "Dienstenmarkt", "Reünieconcert", "Afsluiting wisselexpositie", "Seniorenfestival",
                  "Daddy Cool Turns 50 – Boney M 1976- 2026", "Muziekweekend: Gouwe Ouwe door Haagse Roots",
                  "Oktoberfest", "Spokentocht Buinerveen", "Lichtjesavond begraafplaats", "Mienskip-sjongen",
                  # namen die op een regel lijken maar het niet zijn
                  "Bridge over Troubled Water – The Simon & Garfunkel Story", "Deadline", "Slotdag Zomerfestival",
                  "Jazzborrel met Trio X", "Inloopdag atelier Geert", "Wandeling langs de dammen",
                  "Concert X voorverkoop gestart", "Dutch Open Darts 2027", "Beurs Bouwplan, Thuis in Wonen",
                  "Br. Bas en de Fanfare",
                  "Pater Moeskroen in concert", "Workshop meditatie", "Boekpresentatie: De moed van vergeving",
                  "+ Def Americans - Johnny Cash Tribute"):
        assert not not_an_outing(_event(title)), title


def test_naam_zonder_schermlezertekst_en_maar_een_keer():
    assert clean_title("Vaiana (opent bij de bron)") == "Vaiana"
    assert clean_title("Taalcafé Taalcafé") == "Taalcafé"
    assert clean_title("Werken met DigiD Werken met DigiD") == "Werken met DigiD"
    assert clean_title("Kinderboekenweek: Spot aan! - met Mark in de bieb! Kinderboekenweek: Spot aan! - m") == \
        "Kinderboekenweek: Spot aan! - met Mark in de bieb!"
    # Een naam die echt zo heet, blijft.
    for title in ("Bye Bye", "New York, New York", "Mambo Mambo"):
        assert clean_title(title) == title


def test_een_emailadres_is_geen_link():
    assert canonical_url("http://luistertafel.klassiek@societeitdeharmonie.nl") == ""
    raw = {"title": "Fossielenwandeling", "startDate": "2026-10-20", "city": "Groningen",
           "verificationStatus": "organizer_confirmed",
           "eventUrl": "http://landschapstafel@societeitdeharmonie.nl\xa0",
           "sourceUrl": "https://societeitdeharmonie.nl/agenda\xa0"}
    event = to_v2(raw, TODAY)
    # De link naar de agenda blijft, zonder de onzichtbare spatie; het e-mailadres valt weg.
    assert event["url"] == "https://societeitdeharmonie.nl/agenda"
    assert [s["url"] for s in event["sources"]] == ["https://societeitdeharmonie.nl/agenda"]
    # Is ook de bron een e-mailadres, dan wordt de agenda waar het uitje op stond de link.
    raw.update(sourceUrl="http://landschapstafel@societeitdeharmonie.nl", sourceRoot="https://www.societeitdeharmonie.nl/")
    event = to_v2(raw, TODAY)
    assert event["url"] == "https://www.societeitdeharmonie.nl/"
    assert [s["host"] for s in event["sources"]] == ["societeitdeharmonie.nl"]


def test_vaste_activiteit_met_datum_in_de_naam():
    def ev(day):
        when = TODAY + timedelta(days=day)
        months = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september",
                  "oktober", "november", "december"]
        return {"title": f"Dorpskamer met spelletjes {when.day} {months[when.month - 1]}", "kind": "overig",
                "occurrences": [{"date": when.isoformat()}], "sources": [{"host": "dorp.example"}]}
    events = [ev(14 * i) for i in range(5)]
    assert routines(events) == set(range(5))


def test_om_middernacht_beginnen_is_tijd_onbekend():
    from pipeline.v2.convert import parse_time_range
    assert parse_time_range("00:00") == (None, None)
    assert parse_time_range("00:00 – 11:45") == (None, None)
    assert parse_time_range("21:00 – 00:00") == ("21:00", "00:00")   # tot middernacht mag wel


def test_film_in_de_bioscoop_blijft_film():
    from pipeline.v2.classify import classify
    event = {"title": "Yellow Letters", "url": "https://sliekerfilm.nl/film/yellow-letters/",
             "pageHints": {"soort": "kunst", "woord": "kunst"},
             "sources": [{"host": "sliekerfilm.nl", "url": "https://sliekerfilm.nl/film/yellow-letters/"}]}
    assert classify(event)["kind"] == "film"


def test_duitse_versie_naast_de_nederlandse_valt_weg():
    from pipeline.v2.build import translations

    def ev(title, path):
        return {"title": title, "url": f"https://ontdekwec.nl{path}", "occurrences": [{"date": "2026-10-15", "startTime": "15:30"}],
                "sources": [{"host": "ontdekwec.nl"}]}
    events = [ev("Ausflug mit Robbenspotting", "/de/agenda/"), ev("Zeehondenkijktocht", "/agenda/"),
              ev("Wattwanderung", "/de/agenda/wad")]
    events[2]["occurrences"][0]["startTime"] = "10:00"   # alleen in het Duits: dan blijft hij staan
    assert translations(events) == {0}


def test_ronde_van_15_oktober():
    """Tweede zoektocht in de live agenda: liturgie, retraites, leden, cursussen, rommel en circuitdagen."""
    for title in ("Cantatedienst", "Choral Evensong", "Kokoro-sesshin", "Zen weekend", "Avond over Suttas",
                  "Lichtcirkel-sessies", "Mantra zingen", "5Ritmes Dans", "Klankschaalbeleving",
                  "Deel activiteit", "Terugkerende activiteit", "Eigenschappen", "Tijdstip", "Plaza 12", "All Dates",
                  "Vaarbewijs 1 les 3", "Inauguratie diner", "Blousenfeest", "Winterstop 19", "Kiezelweek 8",
                  "Feestavond vrienden van SC Erica", "Kaartavond", "Halloweenparty VV Suameer",
                  "Âlderein activiteit: BINGO", "Jiergearkomste Pleatslik NUT", "Vergaderingen Dorpsbelangen",
                  "Inloopkwartier Dorpsbelang", "Peutergym", "Power Yoga Gevorderd", "Inloopmoment Warten – sociaal werker",
                  "Inloopavond nieuwbouw", "OPEN CALL: Noorderlicht Biënnale", "LeukeSpulletjes is geopend",
                  "Bekendmaking geboorte nieuwe inwoner", "PureDriving", "Rensportschool Zandvoort",
                  "Amnesty International schrijfochtend"):
        assert not_an_outing(_event(title)), title
    for title in ("Benefietmaaltijd – Doperse Dis", "Meditatief klankschalenconcert", "Sound Bath | Klank Ligconcert",
                  "Workshop koperslaan voor beginners", "Inloopdag atelier Geert", "TT Assen", "Dutch Racing Series",
                  "(Verkoop) expositie Gerrit Offringa", "Woorden op Woensdag", "Kerstconcert",
                  # gevonden bij het nakijken door een frisse hulpagent
                  "Sinterklaasviering Ondernemersvereniging Diever", "Concert Muziekvereniging Excelsior",
                  "Kerstmarkt Ondernemersvereniging Zuidlaren", "Mikstoernooi/Famyljedei VV Suameer", "Expositie is geopend",
                  "Open les 1", "Winterstop toernooi", "Open klaverjasavond: kaartavond voor iedereen",
                  "Deuren open 20:00 - Racoon live", "Opening nieuwbouw bibliotheek", "Schrijfavond met auteur Arnon Grunberg"):
        assert not not_an_outing(_event(title)), title


def test_samen_eten_en_bingo_in_het_dorp_is_niet_noemenswaardig():
    """Afspraak van 16 oktober 2026 (voorbeeld 'Visje eten' in Dörpshoes Nijland)."""
    def at(title, venue=None):
        return {"title": title, "url": "https://dorp.example/agenda/x", "venue": {"name": venue, "city": "Nijland"},
                "sources": [{"type": "organisator", "url": "https://dorp.example/agenda/x", "host": "dorp.example"}]}

    for title in ("Visje eten", "Mosselen eten", "Kerstbingo", "Bingo avond", "Najaarsbingo van de Oranjevereniging",
                  "Kinderbingo", "Turks koken", "Koken met de Wegwijzer", "Keallepoat kafee", "Spieksters aan toavel",
                  "Heel Spijk Bakt", "Eetcafé Vlamboyant", "Koningsontbijt 2027"):
        assert not_an_outing(at(title)), title
    for title, venue in (("High Tea met bingo", "MFC Schildwolde"), ("LA NOTTE ITALIANA – EEN ITALIAANSE AVOND", "Dorpshuis De Vrijwilliger"),
                         ("Proeverij", "MFA Dorpshuis Yders Hoes")):
        assert not_an_outing(at(title, venue)), title
    # Wat wel een uitje is, blijft staan: een show, muziek, proeverij van wijn of bier, een kookworkshop.
    for title, venue in (("Maartje en Kine – DE BINGO SHOW", "De Oosterpoort"), ("Kerstballen Muziekbingo", "Huize Maas"),
                         ("Bingo met na afloop live muziek", "Sparta Kantine"), ("Bierproeverij", "Dorpshuis Over Entinghe"),
                         ("Kookworkshop Italiaans", None), ("Dorps – Theaterdiner", "Dorpshuis Niehove"),
                         ("Wijnproeverij", "MFC It Joo"), ("Whiskey Festival Groningen", "Der Aa-kerk")):
        assert not not_an_outing(at(title, venue)), title
