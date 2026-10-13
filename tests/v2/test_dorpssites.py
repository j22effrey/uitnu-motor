"""Dorpswebsites zoeken: per plaats in het werkgebied kijken of er een eigen website is."""
import json
from urllib.error import HTTPError

from collector import discover_venues as dv
from collector import source_probe as probe
from collector import village_sites as vs
from collector.site_crawler import Fetched
from collector.source_activation import default_place_for

EENRUM = {"qid": "Q1", "naam": "Eenrum", "namen": ["Eenrum"], "soort": "dorp", "lat": 53.36, "lon": 6.46,
          "gemeenten": ["Het Hogeland", "De Marne"], "provincies": ["Groningen"], "postcodes": ["9967"],
          "websites": [], "dubbeleNaam": False}
NEARBY = [" pieterburen ", " mensingeweer ", " kloosterburen "]
VILLAGE_PAGE = ("<html><head><title>Home - Dorpsbelangen Eenrum</title></head><body><nav>Agenda Nieuws</nav>"
                "<p>Welkom op de website van Vereniging Dorpsbelangen Eenrum. Ons dorp in de gemeente Het Hogeland "
                "heeft een actief dorpshuis, een ijsvereniging en veel activiteiten voor jong en oud. Samen met "
                "Pieterburen en Mensingeweer organiseren we elk jaar de dorpsfeesten.</p>"
                "<footer>Hoofdstraat 1, 9967 PB Eenrum</footer></body></html>")


def _wd(qid, label, kind="Q532", point="POINT(6.46 53.36)", **extra):
    row = {"item": {"value": f"http://www.wikidata.org/entity/{qid}"}, "label": {"value": label},
           "coord": {"value": point}, "type": {"value": f"http://www.wikidata.org/entity/{kind}"}}
    row.update({key: {"value": value} for key, value in extra.items()})
    return row


def test_websitenamen_die_dorpen_gebruiken():
    guesses = vs.domain_guesses({"naam": "Nieuw-Beerta", "namen": ["Nieuw-Beerta"], "soort": "dorp",
                                 "provincies": ["Groningen"]})
    for domain in ("nieuwbeerta.nl", "nieuw-beerta.nl", "dorpsbelangennieuwbeerta.nl", "dorpsbelangen-nieuw-beerta.nl",
                   "nieuwbeerta.com", "mfcnieuwbeerta.nl", "nieuwbeerta-groningen.nl"):
        assert domain in guesses
    assert guesses[0] == "nieuwbeerta.nl"                                  # de meest gebruikte eerst
    hamlet = vs.domain_guesses({"naam": "Froombosch", "soort": "gehucht"})
    assert "froombosch.com" in hamlet and "mfcfroombosch.nl" not in hamlet  # een gehucht: alleen de gewone namen
    assert vs.domain_guesses({"naam": "Groningen", "soort": "stad"}) == []  # een grote stad heeft geen dorpssite
    assert vs.slugs("'t Zandt") == ("tzandt", "t-zandt") and vs.slugs("Damwâld") == ("damwald", "damwald")


def test_plaatsen_uit_wikidata_met_gemeente_postcode_en_friese_naam():
    payload = {"results": {"bindings": [
        _wd("Q1", "Eenrum", postcode="9967", gemeenteLabel="Het Hogeland", provincieLabel="Groningen"),
        _wd("Q1", "Eenrum", gemeenteLabel="De Marne"),                         # vroegere gemeente
        _wd("Q2", "Damwoude", fy="Damwâld", website="damwoude.nl"),
        _wd("Q3", "Q12345"),                                                   # geen naam: overslaan
        _wd("Q4", "Pasop", kind="Q5084"),
        _wd("Q5", "Eijsden", point="POINT(5.71 50.78)"),                    # ver buiten het werkgebied
    ]}}
    places = {p["qid"]: p for p in vs.places_from_wikidata(payload)}
    assert set(places) == {"Q1", "Q2", "Q4"}
    assert places["Q1"]["gemeenten"] == ["Het Hogeland", "De Marne"] and places["Q1"]["postcodes"] == ["9967"]
    assert places["Q2"]["namen"] == ["Damwoude", "Damwâld"] and places["Q2"]["websites"] == ["https://damwoude.nl/"]
    assert places["Q4"]["soort"] == "gehucht" and places["Q1"]["soort"] == "dorp"
    assert "P281" in vs.places_query() and "PREFIX wdt:" in vs.places_query()


def test_plaatsenlijst_bij_een_storing_van_wikidata_bij_de_kopie_halen(monkeypatch):
    asked = []

    def fake(url, data=None, timeout=0):
        asked.append(url)
        if "query.wikidata.org" in url:
            raise OSError("429 te druk")
        return {"results": {"bindings": []}}

    monkeypatch.setattr(vs, "_fetch_json", fake)
    assert vs.fetch_places() == {"results": {"bindings": []}}
    assert asked == list(vs.SPARQL_ENDPOINTS)


def test_plaatsnamen_die_vaker_voorkomen():
    rows = [{"label": {"value": name}, "coord": {"value": point}} for name, point in [
        ("Zuidwolde", "Point(6.59 53.26)"), ("Zuidwolde", "Point(6.42 52.67)"),   # Groningen en Drenthe
        ("Peize", "Point(6.50 53.15)"),
        ("Eenrum", "Point(6.46 53.36)"), ("Eenrum", "Point(6.461 53.361)"),      # twee items, zelfde plek
    ]]
    assert vs.shared_names({"results": {"bindings": rows}}) == ["zuidwolde"]


def test_oordeel_over_een_voorpagina():
    title, text = vs.page_text(VILLAGE_PAGE)
    verdict, reason = vs.judge_page(EENRUM, title, text, NEARBY)
    assert verdict == "dorpssite" and "gemeente Het Hogeland" in reason and "eigen postcode" in reason
    assert vs.site_name(title, "Eenrum") == "Dorpsbelangen Eenrum"
    # Te koop of geparkeerd, of de plaatsnaam staat er niet op: nee.
    parked = "Deze domeinnaam is te koop! Eenrum.nl kopen? Neem contact op met de eigenaar van dit domein. " * 3
    assert vs.judge_page(EENRUM, "eenrum.nl", parked, NEARBY)[0] == "nee"
    assert vs.judge_page(EENRUM, "Bakkerij", "Brood en banket uit Winsum, al vijftig jaar. " * 5, NEARBY) == (
        "nee", "de plaatsnaam staat niet op de pagina")
    town_hall = "Gemeente Het Hogeland | Eenrum"
    assert vs.judge_page(EENRUM, town_hall, text, NEARBY)[0] == "nee"
    # Geen gemeente, postcode of dorpen in de buurt op de pagina, wel dorpswoorden:
    bare = "Welkom bij het dorpshuis van Eenrum. Zaalhuur, agenda en nieuws van het dorpshuis voor iedereen. " * 2
    assert vs.judge_page(EENRUM, "Dorpshuis Eenrum", bare, NEARBY)[0] == "dorpssite"      # unieke plaatsnaam
    assert vs.judge_page({**EENRUM, "dubbeleNaam": True}, "Dorpshuis Eenrum", bare, NEARBY)[0] == "twijfel"
    # Unieke plaatsnaam, maar niet in de titel of het adres: misschien iemand met die achternaam.
    sculptor = "Beeldhouwster Aly Eenrum uit Biddinghuizen. Ze geeft workshops voor dorpsgenoten en anderen. " * 2
    assert vs.judge_page(EENRUM, "Werken met steen", sculptor, NEARBY)[0] != "dorpssite"
    # Een politieke partij, een uitagenda of vakantiesite is geen dorpssite.
    assert vs.judge_page(EENRUM, "Liberaal Eenrum | Lokale partij", text, NEARBY) == ("nee", "website van een politieke partij")
    assert vs.judge_page(EENRUM, "Wat te doen in Eenrum vandaag?", text, NEARBY)[0] == "twijfel"
    assert vs.judge_page(EENRUM, "Huur een huisje in Eenrum", text, NEARBY)[0] == "twijfel"
    # Een postcode van elders telt tegen: dan is het (waarschijnlijk) een dorp met dezelfde naam.
    elsewhere = bare + " Adres: Dorpsstraat 3, 7921 AB Eenrum."
    assert vs.judge_page(EENRUM, "Dorpshuis", elsewhere, NEARBY) == (
        "nee", "hoort misschien bij een andere plaats: postcode van elders")
    # Een bedrijf in de streek is geen dorpssite.
    shop = ("Webshop Eenrum in de gemeente Het Hogeland: bestellen, offerte aanvragen, gratis verzending. "
            "Bezoek ook onze winkel in Pieterburen en Mensingeweer. ") * 2
    assert vs.judge_page(EENRUM, "Webshop", shop, NEARBY)[0] == "nee"
    # Een websitenaam als dorpsbelangeneenrum.nl telt als dorpswoord.
    plain_page = "Eenrum. Nieuws, agenda en foto's. Kijk ook bij de vereniging. Contact via het formulier. " * 2
    assert vs.judge_page(EENRUM, "Home", plain_page, NEARBY, host="dorpsbelangeneenrum.nl")[0] == "dorpssite"
    # Postcode: dezelfde eerste drie cijfers is 'uit de buurt'; alleen de eerste twee zegt niets
    # (9163 Nes op Ameland is niet 9142 Nes bij Dokkum).
    nes = {**EENRUM, "naam": "Nes", "namen": ["Nes"], "gemeenten": [], "postcodes": ["9142"]}
    assert vs.region_score(nes, "Dorpsbelang Nes, 9163 AB Nes", []) == (0, [])
    assert vs.region_score(nes, "Dorpsbelang Nes, 9143 AB Nes", [])[0] == 2
    # Jaartallen zijn geen postcode.
    assert vs.region_score({**EENRUM, "gemeenten": []}, "Uitslag 2026 NK in Eenrum", []) == (0, [])


def _site_fetcher(pages, log):
    """Nep-internet: pages[url] = (status, tekst) of HTTPError."""
    def fetch(url, timeout=15):
        log.append(url)
        value = pages.get(url, (404, ""))
        if isinstance(value, Exception):
            raise value
        status, text = value
        if status >= 400:
            raise HTTPError(url, status, "x", {}, None)
        return Fetched(url, status, "text/plain" if url.endswith("robots.txt") else "text/html", text)
    return fetch


def test_dorpswebsite_zoeken_met_robots_en_doorverwijzingen():
    moved = HTTPError("https://eenrum.nl/robots.txt", 301, "Moved", {"Location": "https://domeinenbank.nl/"}, None)
    pages = {
        "https://eenrum.nl/robots.txt": moved,                               # te koop bij een domeinhandel
        "https://dorpsbelangeneenrum.nl/": (200, VILLAGE_PAGE),
        "https://eenrum.com/robots.txt": (200, "User-agent: *\nDisallow: /"),
        "https://eenrum.com/": (200, VILLAGE_PAGE),
    }
    log = []
    exists = {"eenrum.nl", "dorpsbelangeneenrum.nl", "eenrum.com"}
    sites = vs.check_place(EENRUM, NEARBY, resolver=lambda host: host in exists, fetcher=_site_fetcher(pages, log))
    verdicts = {s.get("adres", s["url"]): (s["oordeel"], s["reden"]) for s in sites}
    assert verdicts["https://eenrum.nl/"] == ("nee", "verwijst door naar domeinenbank.nl")
    assert verdicts["https://dorpsbelangeneenrum.nl/"][0] == "dorpssite"
    assert verdicts["https://eenrum.com/"] == ("nee", "robots.txt staat de robot niet toe")
    assert "https://eenrum.com/" not in log and "https://domeinenbank.nl/" not in log   # niet gelezen
    # Verhuisd naar een websitenaam met de plaatsnaam erin: die wordt wel gevolgd.
    pages = {"https://eenrum.nl/robots.txt": HTTPError("x", 301, "Moved", {"Location": "https://www.dorp-eenrum.nl/"}, None),
             "https://www.dorp-eenrum.nl/": (200, VILLAGE_PAGE)}
    site = vs.check_site("https://eenrum.nl/", EENRUM, NEARBY, fetcher=_site_fetcher(pages, []))
    assert (site["url"], site["oordeel"]) == ("https://www.dorp-eenrum.nl/", "dorpssite")


def test_officiele_website_van_de_gemeente_bij_meerdere_plaatsen_overslaan(tmp_path):
    shared = {**EENRUM, "websites": ["https://www.hethogeland.nl/"]}
    other = {**EENRUM, "qid": "Q2", "naam": "Pieterburen", "namen": ["Pieterburen"], "websites": ["https://www.hethogeland.nl/"]}
    log = []
    store = {}
    report = vs.run([shared, other], store, resolver=lambda host: False, fetcher=_site_fetcher({}, log), today="2026-10-12")
    assert report["nagelopen"] == 2 and log == []          # de gemeentesite hoort bij geen van beide als dorpssite
    assert store["plaatsen"]["Q1"]["gekekenOp"] == "2026-10-12" and store["plaatsen"]["Q1"]["sites"] == []


def test_plaatsen_komen_na_een_tijd_opnieuw_aan_de_beurt():
    day = vs.date(2026, 10, 12)
    assert vs.place_due(None, day)
    assert not vs.place_due({"gekekenOp": "2026-09-01", "sites": []}, day)
    assert vs.place_due({"gekekenOp": "2026-07-01", "sites": []}, day)                       # na 90 dagen
    assert vs.place_due({"gekekenOp": "2026-09-20", "sites": [{"oordeel": "fout"}]}, day)    # storing: na 14 dagen
    store = {"plaatsen": {"Q1": {"gekekenOp": "2026-10-01", "sites": []}}}
    places = [EENRUM, {**EENRUM, "qid": "Q2", "naam": "Pieterburen", "namen": ["Pieterburen"]}]
    report = vs.run(places, store, resolver=lambda host: False, fetcher=_site_fetcher({}, []), today="2026-10-12")
    assert report["aanDeBeurt"] == 1 and store["plaatsen"]["Q2"]["naam"] == "Pieterburen"


def test_gevonden_dorpssites_gaan_naar_de_wachtrij_met_de_plaats(tmp_path):
    store, queue, known, tips = tmp_path / "dorpssites.json", tmp_path / "q.json", tmp_path / "k.json", tmp_path / "t.json"
    store.write_text(json.dumps({"plaatsen": {"Q1": {"naam": "Eenrum", "lat": 53.36, "lon": 6.46, "sites": [
        {"url": "https://dorpsbelangeneenrum.nl/", "oordeel": "dorpssite", "naam": "Dorpsbelangen Eenrum"},
        {"url": "https://eenrum.info/", "oordeel": "twijfel", "naam": "Eenrum info"},
    ]}}}))
    known.write_text(json.dumps({"sources": []}))
    assert dv.main(["--queue", str(queue), "--known", str(known), "--tips", str(tips), "--village-sites", str(store),
                    "--tips-only"]) == 0
    [item] = json.loads(queue.read_text())["candidates"]                     # twijfel niet
    assert item["host"] == "dorpsbelangeneenrum.nl" and item["areaStatus"] == "binnen"
    assert item["evidence"][0]["anchorText"] == "Dorpsbelangen Eenrum (dorpssite, Eenrum)"
    # De uitjes krijgen de plaats van het dorp (zonder vaste zaal: ze zijn overal in het dorp).
    assert default_place_for(item, role="venue") == {"city": "Eenrum", "lat": 53.36, "lon": 6.46}
    # Testen: eerst tips, dan nieuwe dorpssites, dan de rest.
    queue.write_text(json.dumps({"candidates": [
        {"host": "nieuw.example", "url": "https://nieuw.example/", "probeStatus": "pending"},
        {"host": "gemeente.example", "url": "https://gemeente.example/", "probeStatus": "pending",
         "evidence": [{"kind": "wikidata"}]},
        {**item, "probeStatus": "pending"},
        {"host": "tip.example", "url": "https://tip.example/", "probeStatus": "pending", "evidence": [{"kind": "tip"}]},
    ]}))
    tested = []

    def fake_probe(url, **kw):
        tested.append(url.split("/")[2])
        return probe.ProbeResult(url, url.split("/")[2], "allowed", "no_supported_extractor", [], None, {})

    original = probe.probe_source
    probe.probe_source = fake_probe
    try:
        probe.probe_queue(queue, limit=4, workers=1, today="2026-10-12")
    finally:
        probe.probe_source = original
    # Gemeenten en festivals (Wikidata) voor de andere nieuwe websites: daar staan de grote evenementen.
    assert tested == ["tip.example", "dorpsbelangeneenrum.nl", "gemeente.example", "nieuw.example"]
