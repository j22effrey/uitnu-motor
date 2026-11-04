"""Grote evenementen (pipeline/v2/groot.py): wat veel publiek trekt licht de site uit (eigenaar, 3 november 2026)."""
from pipeline.v2 import groot

REGISTER = groot.load_register()


def _event(title, kind="feest", city="Winschoten", venue=None, host="dorp.example", **extra):
    return {"title": title, "kind": kind, "tags": [], "venue": {"name": venue or city, "city": city},
            "sources": [{"host": host}], "occurrences": [{"date": "2026-11-14"}], **extra}


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


def test_vaak_terug_is_niet_bijzonder_maar_meerdaags_wel():
    weekly = [_event("Braderie Hollum", kind="markt", city="Hollum") for _ in range(5)]
    for i, event in enumerate(weekly):
        event["occurrences"] = [{"date": f"2027-07-{7 + 7 * i:02d}"}]
    town = [_event(f"Concert {i}", kind="muziek", city="Winschoten", host=f"podium{i}.example") for i in range(groot.BIG_PLACE)]
    fair = [_event("Kermis Winschoten", kind="feest") for _ in range(6)]
    for i, event in enumerate(fair):
        event["occurrences"] = [{"date": f"2026-10-{28 + i:02d}"}] if i < 4 else [{"date": f"2026-11-0{i - 3}"}]
    assert groot.mark(weekly + town + fair, REGISTER) == 6  # de kermis (zes dagen), niet de wekelijkse braderie


def test_samenstellingen_en_alleen_in_een_grotere_plaats():
    town = [_event(f"Concert {i}", kind="muziek", city="Leeuwarden", host=f"podium{i}.example") for i in range(groot.BIG_PLACE)]
    big = [_event("Sinterklaasintocht Leeuwarden", city="Leeuwarden"), _event("Voorjaarskermis", city="Leeuwarden"),
           _event("Bloemencorso Eelde", city="Eelde"), _event("Lemster Dickens Festijn", city="Lemmer")]
    # Een dorp met één drukke dorpswebsite blijft een dorp.
    small = [_event("Intocht Sinterklaas", city="Tzum"), _event("Koningsdag", city="Lauwerzijl"),
             _event("Fakkel optocht", city="Bontebok"), _event("Dickens Kerstfair", city="Haulerwijk"),
             _event("Intocht Sinterklaas", city="Leeuwarden", venue="Dorpshuis Ous Hoes")] + [_event(f"Activiteit {i}", city="Tzum") for i in range(30)]
    events = town + big + small
    groot.mark(events, REGISTER)
    assert all(e.get("groot") for e in big)
    assert not any(e.get("groot") for e in small)


def test_niet_groot_kijken_en_kaarten():
    for title in ("World Cup kijken in café", "TT Assen kijken op groot scherm", "Vuurwerk opruimen", "Vuurwerkverkoop",
                  "Feestweek: seniorenmiddag", "Kermis: kaartavond", "Bridgemarathon", "Marathon Cup 4"):
        assert not reason(_event(title, kind="sport")), title


def test_mark_zet_tag_en_reden():
    town = [_event(f"Concert {i}", kind="muziek", host=f"podium{i}.example") for i in range(groot.BIG_PLACE)]
    events = [_event("Intocht Sinterklaas"), _event("Concert", kind="muziek")] + town
    assert groot.mark(events, REGISTER) == 1
    assert events[0]["tags"] == ["groot"] and events[0]["groot"].startswith("publiekstrekker")
    assert "groot" not in events[1] and events[1]["tags"] == []
    assert groot.summary(events)["aantal"] == 1


def test_gemeente_zonder_werkende_agenda_valt_op():
    """Les van Adrillen: een gemeente die de motor weigert, was nooit een bron en viel nergens op."""
    from pipeline.v2.dekking import municipalities
    register = {"gemeenten": [
        {"naam": "Veendam", "website": "https://www.veendam.nl/", "agenda": ["veendam-kalender"]},
        {"naam": "Ooststellingwerf", "website": "https://www.ooststellingwerf.nl/", "agenda": ["uutgaon"]},
        {"naam": "Oldambt", "website": "https://www.gemeente-oldambt.nl/", "agenda": []},
        {"naam": "Pekela", "website": "https://www.pekela.nl/", "agenda": ["pekela-oud"], "opmerking": "geen kalender"},
        "kapotte regel",
    ]}
    sources = [{"id": "veendam-kalender", "rootUrl": "https://www.veendam.nl/"},
               {"id": "uutgaon", "rootUrl": "https://www.uutgaon.nl/"},
               {"id": "pekela-oud", "rootUrl": "https://www.pekela.nl/", "enabled": False}]
    candidates = {"candidates": [{"host": "gemeente-oldambt.nl", "probeStatus": "error", "lastError": "robots.txt niet bereikbaar"}]}
    # Wat de bronnen deze ronde ophaalden; pekela.nl en gemeente-oldambt.nl alleen via losse uitjes (tellen niet).
    result = municipalities(register, sources, candidates, {"veendam.nl", "uutgaon.nl"})
    assert result["totaal"] == 4 and result["metAgenda"] == 2
    why = {row["naam"]: row["waarom"] for row in result["zonderAgenda"]}
    assert "storing" in why["Oldambt"] and "robots.txt niet bereikbaar" in why["Oldambt"]
    assert why["Pekela"].startswith("geen kalender") and "pekela-oud staat uit" in why["Pekela"]
    # Een bron die aan staat maar niets ophaalt, staat er eerlijk bij.
    idle = municipalities(register, sources, candidates, {"uutgaon.nl"})
    assert "veendam-kalender staat aan maar haalde geen komende uitjes op" in {r["naam"]: r["waarom"] for r in idle["zonderAgenda"]}["Veendam"]


def test_lichtparade_winterfair_en_sinterklaas_komt():
    town = [_event(f"Concert {i}", kind="muziek", city="Groningen", host=f"podium{i}.example") for i in range(groot.BIG_PLACE)]
    big = [_event("Sunnemeerten Parade (lichtparade)", city="Groningen"), _event("Stadjersmarkt 2026", kind="markt", city="Groningen"),
           _event("Sinterklaas komt naar Groningen!", city="Groningen")]
    # Een winterfair of kerstmarkt is meestal klein (school, kerk, wijk): alleen via groot.json (WinterWelVaart, Dickens).
    small = [_event("Winterfair Groningen", kind="markt", city="Groningen"), _event("Kerstmarkt Camminghaburen", kind="markt", city="Groningen"),
             _event("Sint Maarten lampionoptocht 2026", city="Groningen")]
    events = town + big + small
    groot.mark(events, REGISTER)
    assert all(e.get("groot") for e in big)
    assert not any(e.get("groot") for e in small)
