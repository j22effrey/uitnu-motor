"""Alle plaatsen: plekken zonder website in OpenStreetMap, en de dekkingscontrole voor het hele werkgebied."""
from datetime import date

from collector import plek_websites
from collector.discover_venues import discoveries_from_place_sites
from collector.site_crawler import Fetched
from pipeline.v2.dekking import auto_register, coverage, merge_registers


def test_websitenamen_raden_uit_de_naam():
    guesses = plek_websites.domain_guesses("Landgoed Tenaxx Dinopark")
    assert "dinoparklandgoedtenaxx.nl" in guesses and "tenaxx.nl" in guesses and "landgoedtenaxx.nl" in guesses
    assert plek_websites.own_words("Landgoed Tenaxx Dinopark") == ["tenaxx"]
    assert plek_websites.domain_guesses("Museum") == []  # alleen algemene woorden: niet te raden


def test_hoort_de_website_bij_de_plek():
    place = {"naam": "Landgoed Tenaxx Dinopark", "plaats": "Wedde"}
    text = "Welkom bij het dinopark in Wedde, Groningen. " * 10
    assert plek_websites.judge(place, "Dinopark & Landgoed Tenaxx", text)[0] == "gevonden"
    assert plek_websites.judge(place, "Welkom", text + " Tenaxx")[0] == "twijfel"        # naam niet in de titel
    assert plek_websites.judge(place, "Iets anders", "Een website over iets anders. " * 10)[0] == "nee"
    assert plek_websites.judge(place, "Tenaxx", "Deze domeinnaam is te koop bij onze domeinhandel")[0] == "nee"


def test_een_gevonden_website_wordt_gecontroleerd_met_robots_txt():
    pages = {"https://www.dinoparklandgoedtenaxx.nl/robots.txt": Fetched("https://www.dinoparklandgoedtenaxx.nl/robots.txt", 200, "text/plain", "User-agent: *\nDisallow:"),
             "https://www.dinoparklandgoedtenaxx.nl/": Fetched("https://www.dinoparklandgoedtenaxx.nl/", 200, "text/html",
                                                          "<title>Dinopark &amp; Landgoed Tenaxx</title>" + "<p>Een dagje uit in Groningen.</p>" * 20)}

    def fetch(url, timeout=12):
        if url not in pages:
            raise OSError("bestaat niet")
        return pages[url]

    place = {"id": "way/1", "naam": "Landgoed Tenaxx Dinopark", "soort": "pretpark", "plaats": "", "lat": 53.07, "lon": 7.02}
    result = plek_websites.check_place(place, resolver=lambda host: host == "www.dinoparklandgoedtenaxx.nl", fetcher=fetch)
    assert result["oordeel"] == "gevonden" and result["url"] == "https://www.dinoparklandgoedtenaxx.nl/"


def test_gevonden_plekken_gaan_de_wachtrij_in(tmp_path):
    store = tmp_path / "plekwebsites.json"
    store.write_text('{"plekken": {"way/613530834": {"naam": "Landgoed Tenaxx Dinopark", "soort": "pretpark", "plaats": "Wedde",'
                     ' "lat": 53.07, "lon": 7.02, "url": "https://www.dinoparklandgoedtenaxx.nl/", "oordeel": "gevonden"},'
                     ' "node/2": {"naam": "Twijfel", "soort": "museum", "url": "https://x.nl/", "oordeel": "twijfel"}}}', encoding="utf-8")
    found = discoveries_from_place_sites(store)
    assert len(found) == 1
    assert found[0]["anchor_text"] == "Landgoed Tenaxx Dinopark (theme_park, Wedde)" and found[0]["kind"] == "osm"


def test_dekking_voor_elke_plaats_uit_de_wachtrij():
    candidates = {"candidates": [
        {"host": "dinoparklandgoedtenaxx.nl", "url": "https://www.dinoparklandgoedtenaxx.nl/", "activationStatus": "active",
         "probeStatus": "supported", "evidence": [{"anchorText": "Landgoed Tenaxx Dinopark (theme_park, Wedde)"}]},
        {"host": "theaterx.nl", "url": "https://theaterx.nl/", "activationStatus": "candidate", "probeStatus": "no_supported_extractor",
         "evidence": [{"anchorText": "Theater X (theatre, Assen)"}]},
        {"host": "spotgroningen.nl", "url": "https://www.spotgroningen.nl/", "evidence": [{"anchorText": "Oosterpoort (theatre, Groningen)"}]},
        {"host": "kerk.nl", "url": "https://kerk.nl/", "evidence": [{"anchorText": "Kerk (place_of_worship, Assen)"}]},
        {"host": "ver.nl", "url": "https://ver.nl/", "areaStatus": "buiten", "evidence": [{"anchorText": "Ver (theatre, Zwolle)"}]},
    ]}
    found = auto_register(candidates, manual_hosts={"spotgroningen.nl"})
    assert sorted(found["plaatsen"]) == ["Assen", "Wedde"]
    events = [{"id": "e1", "sources": [{"host": "dinoparklandgoedtenaxx.nl"}], "occurrences": [{"date": "2026-10-24"}]}]
    result = coverage(events, merge_registers({"plaatsen": {}}, found), date(2026, 10, 16))
    assert result["goed"] == 1 and [r["naam"] for r in result["ontbreekt"]] == ["Theater X"]
    assert result["ontbreekt"][0]["waarom"].startswith("de test vond geen leesbare agenda")
    assert result["perSoort"] == {"theater": {"ontbreekt": 1, "teWeinig": 0}} and result["ontbreektTotaal"] == 1


def test_een_plaatsnaam_is_nooit_de_website_van_een_plek():
    plek_websites.PLACE_NAMES.update({"assen", "groningen", "hoogeland"})
    assert plek_websites.domain_guesses("Theater Assen", town="Assen") == []        # nooit assen.com (stadsmarketing)
    assert "groningen.nl" not in plek_websites.domain_guesses("Pathé Groningen", town="Groningen")
    place = {"naam": "Tenaxx", "plaats": "Wedde"}
    assert plek_websites.judge(place, "Wedde", "Welkom in Wedde, Groningen. Tenaxx " * 10)[0] == "nee"


def test_uitgesloten_en_uitgezette_websites_tellen_niet_mee_in_de_dekking():
    candidates = {"candidates": [
        {"host": "maze.nl", "url": "https://maze.nl/groningen", "evidence": [{"anchorText": "Maze (cinema, Groningen)"}]},
        {"host": "oud.nl", "url": "https://oud.nl/", "evidence": [{"anchorText": "Oud Theater (theatre, Sneek)"}]},
    ]}
    assert auto_register(candidates, skip_hosts={"oud.nl"}) == {"plaatsen": {}}
