"""Indeling voor de nieuwe bronnen in Friesland en Drenthe (proef van 13 oktober: 17% 'overig' -> 7%).
Friese titels, wedstrijden met een lang streepje, kopjes van websites en vaste clubzaken."""
from pipeline.v2.classify import classify, not_an_outing


def _event(title, host="dorpshuis.example", path="/agenda/x"):
    url = f"https://{host}{path}"
    return {"title": title, "url": url, "sources": [{"type": "organisator", "url": url, "host": host}]}


def test_friese_en_drentse_activiteiten_krijgen_een_soort():
    cases = {
        "Covos DS1 – VC Sneek DS2": "sport", "Beker: SDS 1 – Kollum 1": "sport", "Foarút 1 – SDS 1": "sport",
        "Meinte Sixmatoernoai": "sport", "Picklebal": "sport", "Kickboksen": "sport", "Loopgroep Terloops": "sport",
        "Stoelfit voor ouderen": "sport", "ISU EK Allround & Sprint": "sport", "Dammen": "sport",
        "Long Covid cafe": "lezing", "De schrijver aan het woord: Gerwin van der Werf": "lezing",
        "Voorlichtingsavond Veiligheid": "lezing", "Klankschaalbeleving": "lezing", "Drents Veurlezen": "lezing",
        "Herfsttij retraite: leven als een kloosterling": "lezing", "Fotograferen met je smartphone": "lezing",
        "Jeugdsoos Dwingeloo": "kinderen", "SoepUur": "eten", "Vrijdagmiddagcafé": "eten",
        "Martens Cantorij": "muziek", "Bazaar": "markt", "Kerstboomverkoop": "markt",
        "Houtdag Kuinderbos": "natuur", "Snoekfiskje foar de jeugd": "natuur", "4 mei herdenking": "kunst",
        "Oliebollen bridgedrive": "feest", "Paasmiddag voor ouderen": "feest", "Forró van Groningen": "feest",
    }
    for title, kind in cases.items():
        assert classify(_event(title))["kind"] == kind, title


def test_festival_en_wedstrijden_per_website():
    # Het hele programma van Explore the North hoort bij het festival (festivalregister, vaste regel 3).
    assert classify(_event("Alabaster DePlume", host="explorethenorth.nl"))["kind"] == "festival"
    assert classify(_event("Hindeloopen", host="www.ifks.frl"))["kind"] == "sport"   # een skûtsjesilen-dag
    assert classify(_event("Gamma Racing Day", host="www.ttcircuit.com"))["kind"] == "sport"


def test_kerk_club_en_mededelingen_zijn_geen_uitje():
    for title in ("Kerkenraad", "Weeksluiting", "Oars as Oars dienst", "Interne Ronde 4",
                  "Externe ronde 2 Philidor 2 – Franeker", "KNVB VC1 Pupillen – Bijeenkomst 3A",
                  "Start fase 2 KNVB Jeugd", "Ald papierkontainer", "Papiercontainer oan é wei",
                  "Vrijwillgersavond dorpshuis", "Griepvaccinaties", "60 jier troud",
                  "Bijeenkomst bestuur dorpshuis en oranjevereniging", "Vrouwen van Kuinre", "Vriendenkring Idaerd"):
        assert not_an_outing(_event(title)), title


def test_kopjes_van_een_website_zijn_geen_uitje():
    for title in ("Fotogalerij", "SPONSOREN GEZOCHT!", "Kom in contact", "Mede mogelijk gemaakt door",
                  "Sfeerimpressie", "Thank you ♥", "Blok 1", "Sign-up", "30 October", "Details",
                  "Wat is er allemaal te beleven", "Uitslag Visserijdagenloterij 2026", "Over ons"):
        assert not_an_outing(_event(title)), title


def test_echte_uitjes_blijven_staan():
    # Een voorstelling die met 'Over de' begint, een club die iets organiseert, een dienst-achtig woord in een naam.
    for title in ("Over de streep", "Vrouwen van Kuinre organiseren een kerstmarkt", "Kerstconcert in de Mariakerk",
                  "Dienstenmarkt", "Programma-avond met lezing", "Dansavond 50 plus"):
        assert not not_an_outing(_event(title)), title


def test_seks_en_naaktfeesten_nooit_in_de_agenda():
    from collector.discover_venues import is_excluded
    assert is_excluded("https://maze.nl/evenementen/")
    for title in ("Men Only Naked Maze Groningen", "Naakt Dag Mix Maze Hilversum", "T-GIRL PARTY", "Erotische avond",
                  "Swingers party", "Sexy Saturday", "Seks en relaties: XXX party", "Darkroom night"):
        assert not_an_outing(_event(title)), title
    # Een dorp, een slak en een naaktloper in de natuur zijn gewoon goed.
    for title in ("Dorpsfeest Sexbierum", "Lezing over naaktslakken", "Sexbierum bloeit"):
        assert not not_an_outing(_event(title)), title


def test_bron_die_levert_maar_door_een_regel_leeg_raakt_is_niet_kapot():
    from collections import Counter
    from pipeline.v2.gate import run_gate

    def ev(i, host):
        return {"id": str(i), "kind": "muziek", "url": f"https://{host}/{i}", "venue": {"city": "Leek"},
                "occurrences": [{"date": "2026-10-20"}], "sources": [{"host": host, "url": f"https://{host}/{i}"}]}

    previous = [ev(i, "kopjes.example") for i in range(11)] + [ev(100 + i, "podium.example") for i in range(100)]
    new = [ev(100 + i, "podium.example") for i in range(100)]
    # Zonder te weten wat de bron aanleverde: 'ineens leeg' (zo hoort het bij een leesfout).
    assert not run_gate(new, previous, "2026-10-13")["passed"]
    # De bron leverde wel 11 uitjes, maar een nieuwe regel haalde ze weg (kopjes): niet kapot.
    delivered = Counter({"kopjes.example": 11, "podium.example": 100})
    assert run_gate(new, previous, "2026-10-13", delivered=delivered)["passed"]


def test_alleen_uitjes_voor_het_grote_publiek():
    """Geen vaste les of oefenavond van een club, geen competitie van amateurteams, niets alleen voor
    leden of de ouderen van het dorp (vraag van de eigenaar, 13 oktober)."""
    for title in ("Koor", "Shantykoor De Brûskoppen", "Fanfare Swettewyn", "Wandelgroep Wommels", "Wandel je fit!",
                  "Klaverjassen", "🃏 Klaverjaskompetitie (48e editie) in Yn 'e Mande", "Koffieochtend",
                  "Koffie inloop MFC it Stedshûs", "Samen eten", "Ying Yoga", "Stoelgym", "Kickboksen", "Muziekles",
                  "Peutermeespeelochtend Emmens", "Jeugdsoos Dwingeloo", "VitalityClub", "Leesclub Moderne literatuur",
                  "Inloop februari", "Bingo", "Thuiswedstrijd JVV 2", "KNLTB najaarscompetitie Senioren",
                  "Covos DS1 – VC Sneek DS2", "Westerlee 1 - VVS 1", "Oktoberfest (Alleen leden)", "Ledengearkomst vv SDS",
                  "Buurtvereniging Om'e Toer Wijnproeverij", "Kerstmiddag voor ouderen", "Kerstlunch 50+",
                  "Ouderenmiddag met muziek", "50 plus club Sinterklaas"):
        assert not_an_outing(_event(title)), title
    # Openbaar: een concert van het koor, een toernooi, een tributeshow met jaartal,
    # een workshop, een festival voor senioren, een dansavond voor 50-plussers, Club Guy & Roni (dans).
    for title in ("Kerstconcert van het koor", "Klaverjastoernooi", "Bridgedrive", "Prijsklaverjassen",
                  "Daddy Cool Turns 50 – Boney M 1976- 2026", "Workshop bonbons maken", "Seniorenfestival",
                  "Senioren darttoernooi", "Dansavond 50 plus", "Club Guy & Roni – The Current", "Pop-up boekenclub",
                  "Open dag fanfare Swettewyn", "Intocht Sinterklaas"):
        assert not not_an_outing(_event(title)), title
