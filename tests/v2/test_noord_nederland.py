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
                  "Dienstenmarkt", "Programma-avond met lezing", "Ouderenmiddag met muziek"):
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
