"""Grote evenementen (pipeline/v2/groot.py): wat veel publiek trekt licht de site uit (eigenaar, 3 november 2026)."""
from pipeline.v2 import groot

REGISTER = groot.load_register()


def _event(title, kind="feest", city="Winschoten", venue=None, **extra):
    return {"title": title, "kind": kind, "tags": [], "venue": {"name": venue or city, "city": city},
            "occurrences": [{"date": "2026-11-14"}], **extra}


def reason(event, frequent=None):
    return groot.groot_reason(event, REGISTER, frequent or set())


def test_publiekstrekkers_en_stadion():
    assert reason(_event("Adrillen 2027", kind="markt"))
    assert reason(_event("Intocht Sinterklaas Groningen", city="Groningen"))
    assert reason(_event("Braderie Najaarsmarkt Centrum Assen", kind="markt", city="Assen"))
    assert reason(_event("SKS Skûtsjesilen 2027: wedstrijd Grou", kind="sport", city="Grou"))
    assert reason(_event("FC Groningen – Feyenoord", kind="sport", city="Groningen", venue="Euroborg"))
    assert reason(_event("Explore the North festival 2026", kind="festival", city="Leeuwarden"))
    assert reason(_event("Weihnachtsmarkt Meppen", kind="markt", city="Meppen", grensUitje=True))
    assert reason(_event("ESNS 2027 — Eurosonic Noorderslag", kind="festival", city="Groningen"))


def test_niet_groot():
    # Een voorstelling met 'kermis' of 'festival' in de naam, iets kleins en een feest rond een groot evenement.
    assert not reason(_event("Sara Kroos – Prikkelarme kermis", kind="theater"))
    assert not reason(_event("Nee, jouw kop is kermis | Klub Karmijn", kind="feest"))
    assert not reason(_event("Groninger Studenten Cabaret Festival", kind="theater", city="Groningen"))
    assert not reason(_event("Sint Maartenoptocht Bilgaard", city="Leeuwarden"))
    assert not reason(_event("Braderie en vlooienmarkt Eurohal Zuidbroek", kind="markt"))
    assert not reason(_event("ESNS Unofficial afterparty", kind="festival", city="Groningen"))
    assert not reason(_event("Jumbo Flyers Heerenveen – Utrecht Dragons", kind="sport", venue="Thialf"))
    assert not reason(_event("Workshop optochtwagen bouwen"))
    assert not reason(_event("Klaverjassen", kind="overig"))


def test_vaak_terug_is_niet_bijzonder():
    weekly = [_event("Braderie Hollum", kind="markt", city="Hollum") for _ in range(5)]
    for i, event in enumerate(weekly):
        event["occurrences"] = [{"date": f"2027-07-{7 + 7 * i:02d}"}]
    assert groot.mark(weekly, REGISTER) == 0


def test_mark_zet_tag_en_reden():
    events = [_event("Intocht Sinterklaas"), _event("Concert", kind="muziek")]
    assert groot.mark(events, REGISTER) == 1
    assert events[0]["tags"] == ["groot"] and events[0]["groot"].startswith("publiekstrekker")
    assert "groot" not in events[1] and events[1]["tags"] == []
    assert groot.summary(events)["aantal"] == 1
