"""Foto's: eerst de organisator, dan Wikimedia Commons (met maker en licentie), anders geen foto.

Zonder foto toont de site een kaart met alleen tekst; illustraties gebruiken we niet."""
import json
from collections import Counter
from datetime import date, timedelta

from collector import event_photos as ep
from collector.site_crawler import Fetched
from pipeline.v2 import photos
from pipeline.v2.build import build

TODAY = date(2026, 10, 12)


def _v2(title, url, city="Bunne", venue="De Melkfabriek", lat=53.13, lon=6.53):
    return {"title": title, "url": url, "venue": {"name": venue, "city": city, "lat": lat, "lon": lon},
            "sources": [{"type": "organisator", "url": url}]}


# ---------------------------------------------------------------- foto op de pagina

def test_schema_org_foto_gaat_voor_og_image():
    html = """<html><head><meta property="og:image" content="/og.jpg">
    <script type="application/ld+json">{"@type": "MusicEvent", "name": "Wende",
      "image": {"@type": "ImageObject", "url": "https://cdn.example/wende.jpg"}}</script></head></html>"""
    assert ep.extract_page_image(html, "https://podium.example/wende") == ("https://cdn.example/wende.jpg", "schema.org")


def test_og_image_wordt_een_volledig_adres():
    html = '<html><head><meta property="og:image" content="/fotos/kermis.jpg"></head></html>'
    assert ep.extract_page_image(html, "https://dorp.example/kermis") == ("https://dorp.example/fotos/kermis.jpg", "og:image")


def test_logo_en_kleine_plaatjes_tellen_niet():
    logo = """<html><head><meta property="og:image" content="https://a.example/uploads/logo-podium.png">
    <meta name="twitter:image" content="https://a.example/uploads/zaal.jpg"></head></html>"""
    assert ep.extract_page_image(logo, "https://a.example/x") == ("https://a.example/uploads/zaal.jpg", "twitter:image")
    small = """<html><head><meta property="og:image" content="https://a.example/klein.jpg">
    <meta property="og:image:width" content="120"></head></html>"""
    assert ep.extract_page_image(small, "https://a.example/x") == (None, None)
    # Drupal zet alle foto's in /sites/default/files/: dat is geen standaardfoto.
    drupal = '<html><head><meta property="og:image" content="https://b.example/sites/default/files/concert.jpg"></head></html>'
    assert ep.extract_page_image(drupal, "https://b.example/x")[0] == "https://b.example/sites/default/files/concert.jpg"


def test_pagina_met_meerdere_uitjes_alleen_bij_dezelfde_titel():
    html = """<html><script type="application/ld+json">[
      {"@type": "Event", "name": "Wende", "image": "https://p.example/wende.jpg"},
      {"@type": "Event", "name": "Fleddy Melculy", "image": "https://p.example/fleddy.jpg"}]</script></html>"""
    assert ep.extract_page_image(html, "https://p.example/", "Fleddy Melculy")[0] == "https://p.example/fleddy.jpg"
    assert ep.extract_page_image(html, "https://p.example/", "Iets anders") == (None, None)


# ---------------------------------------------------------------- welke foto kiest de fabriek

CACHE = {
    "pages": {
        "https://melk.example/a": {"image": "https://melk.example/a.jpg"},
        "https://melk.example/standaard": {"image": "https://melk.example/huis.jpg"},
    },
    "homepages": {"melk.example": {"image": "https://melk.example/huis.jpg"}},
    "commons": {
        "plek:de melkfabriek|bunne": {"url": "https://upload.example/melkfabriek.jpg", "author": "Jan Jansen",
                                      "license": "CC BY-SA 4.0", "pageUrl": "https://commons.example/File:M.jpg"},
        "plaats:bourtange": {"url": "https://upload.example/bourtange.jpg", "author": "Piet", "license": "CC0"},
        "plaats:groningen": {"url": "https://upload.example/martini.jpg", "author": "Klaas", "license": "CC BY 4.0"},
    },
}


def test_foto_van_de_organisator_met_naam():
    events = [_v2("Concert A", "https://melk.example/a")]
    photos.attach_photos(events, CACHE, {"melk.example": "De Melkfabriek"})
    image = events[0]["image"]
    assert (image["type"], image["match"], image["credit"]) == ("organisator", "uitje", "Foto: De Melkfabriek")
    assert image["url"] == "https://melk.example/a.jpg"


def test_standaardfoto_van_de_website_telt_niet_en_dan_wikimedia_van_de_plek():
    events = [_v2("Concert B", "https://melk.example/standaard")]
    counts = photos.attach_photos(events, CACHE)
    image = events[0]["image"]
    assert (image["type"], image["match"]) == ("wikimedia", "plek")
    assert image["credit"] == "Foto: Jan Jansen · CC BY-SA 4.0 · Wikimedia Commons"
    assert counts == {"organisator": 0, "wikimedia": 1, "zonder": 0}


def test_zonder_voorpagina_alleen_een_foto_die_bij_een_uitje_hoort():
    """Is de voorpagina nog niet bekeken, dan telt een foto die maar bij één uitje staat (en de website heeft
    verschillende foto's per uitje). Een plaatje dat bij meerdere uitjes terugkomt is de standaardfoto."""
    cache = dict(CACHE, homepages={})
    events = [_v2("Concert A", "https://melk.example/a")]
    photos.attach_photos(events, cache)
    assert events[0]["image"]["type"] == "organisator"
    shared = dict(CACHE, homepages={}, pages={**CACHE["pages"], "https://melk.example/b": {"image": "https://melk.example/a.jpg"}})
    events = [_v2("Concert A", "https://melk.example/a")]
    photos.attach_photos(events, shared)
    assert events[0]["image"]["type"] == "wikimedia"
    only = dict(CACHE, homepages={}, pages={"https://solo.example/a": {"image": "https://solo.example/a.jpg"}})
    events = [_v2("Concert A", "https://solo.example/a")]
    photos.attach_photos(events, only)
    assert events[0]["image"]["type"] == "wikimedia"  # één foto van die website: nog niet zeker


def test_agendalijst_geeft_geen_foto_per_uitje():
    cache = dict(CACHE, pages={"https://melk.example/agenda": {"image": "https://melk.example/agenda.jpg"}})
    events = [_v2(t, "https://melk.example/agenda", venue=None, city="Bourtange") for t in ("Markt", "Kermis", "Concert")]
    photos.attach_photos(events, cache)
    assert {e["image"]["match"] for e in events} == {"plaats"}


def test_foto_van_de_plaats_ook_bij_veel_uitjes_daar():
    few = [_v2("Vestingfeest", "https://x.example/1", venue=None, city="Bourtange")]
    photos.attach_photos(few, CACHE)
    assert few[0]["image"]["alt"] == "Bourtange"
    many = [_v2(f"Uitje {i}", f"https://x.example/{i}", venue=None, city="Groningen") for i in range(6)]
    counts = photos.attach_photos(many, CACHE)
    assert counts == {"organisator": 0, "wikimedia": 6, "zonder": 0}
    nowhere = [_v2("Uitje", "https://x.example/z", venue=None, city="Nergenshuizen")]
    assert photos.attach_photos(nowhere, CACHE)["zonder"] == 1 and nowhere[0]["image"] is None


def test_meerdere_fotos_van_een_plaats_om_de_beurt():
    record = {"url": "https://upload.example/1.jpg", "photos": [
        {"url": f"https://upload.example/{i}.jpg", "author": f"Maker {i}", "license": "CC BY 4.0"} for i in (1, 2, 3)]}
    cache = {"commons": {"plaats:groningen": record}}
    events = [dict(_v2(f"Uitje {i}", f"https://x.example/{i}", venue=None, city="Groningen"),
                   id=f"u{i}", occurrences=[{"date": f"2026-11-0{i}"}]) for i in (1, 2, 3, 4)]
    photos.attach_photos(events[::-1], cache)  # de volgorde in de lijst maakt niet uit, de datum wel
    assert [e["image"]["url"].rsplit("/", 1)[1] for e in events] == ["1.jpg", "2.jpg", "3.jpg", "1.jpg"]
    assert events[1]["image"]["credit"] == "Foto: Maker 2 · CC BY 4.0 · Wikimedia Commons"
    # Los gekozen krijgt een uitje steeds dezelfde foto.
    once = photos.choose_photo(events[0], cache, lists=set(), names={})
    assert once == photos.choose_photo(events[0], cache, lists=set(), names={})


def test_plek_is_het_gebouw_zonder_adres():
    event = _v2("Expo", "https://forum.example/", venue="Forum Groningen, Nieuwe Markt 1", city="Groningen")
    assert photos.venue_key(event) == "plek:forum groningen|groningen"
    assert photos.venue_key(_v2("Markt", "https://x.example/", venue="Centrum Delfzijl", city="Delfzijl")) is None


# ---------------------------------------------------------------- Wikidata en Commons

def _wiki(search, entities, commons=None):
    calls = []

    def fetch_json(url, params, **_):
        calls.append(params["action"])
        if params["action"] == "wbsearchentities":
            return {"search": search.get(params["search"], [])}
        if params["action"] == "wbgetentities":
            return {"entities": {i: entities[i] for i in params["ids"].split("|") if i in entities}}
        return commons or {}
    return fetch_json, calls


def _entity(lat, lon, image="Foto.jpg", types=("Q532",)):
    def claim(value):
        return {"mainsnak": {"datavalue": {"value": value}}, "rank": "normal"}
    return {"claims": {"P625": [claim({"latitude": lat, "longitude": lon})], "P18": [claim(image)],
                       "P31": [claim({"id": t}) for t in types]}}


def test_plaats_is_het_dorp_dichtbij_niet_de_provincie_of_een_naamgenoot():
    fetch_json, _ = _wiki(
        {"Haren": [{"id": "Q1", "label": "Haren", "description": "plaats in Duitsland"},
                   {"id": "Q2", "label": "Haren", "description": "dorp in de gemeente Groningen"},
                   {"id": "Q3", "label": "Haren", "description": "provincie", }]},
        {"Q1": _entity(52.79, 7.24, "Ems.jpg"), "Q2": _entity(53.17, 6.60, "Haren.jpg"),
         "Q3": _entity(53.17, 6.61, "Prov.jpg", types=("Q134390",))})
    assert ep.find_place("Haren", (53.17, 6.60), fetch_json)["file"] == "Haren.jpg"
    assert ep.find_place("Haren", (53.80, 7.90), fetch_json) is None  # alles te ver weg


def test_gebouw_moet_op_de_plek_van_het_uitje_staan():
    fetch_json, _ = _wiki({"Neushoorn": [{"id": "Q9", "label": "Neushoorn", "description": "poppodium"}]},
                          {"Q9": _entity(53.20, 5.80, "Neushoorn.jpg", types=("Q1060829",))})
    assert ep.find_venue("Neushoorn", (53.201, 5.801), fetch_json)["file"] == "Neushoorn.jpg"
    assert ep.find_venue("Neushoorn", (53.22, 6.57), fetch_json) is None  # zelfde naam, andere stad


def test_commons_geeft_maker_en_licentie():
    fetch_json, _ = _wiki({}, {}, {"query": {"pages": {"1": {"imageinfo": [{
        "mime": "image/jpeg", "thumburl": "https://upload.example/thumb/1280px-B.jpg",
        "descriptionurl": "https://commons.example/wiki/File:B.jpg",
        "extmetadata": {"Artist": {"value": '<a href="//commons.example/wiki/User:Piet">Piet de Vries</a>'},
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}}}]}}}})
    info = ep.commons_info("B.jpg", fetch_json)
    assert (info["author"], info["license"], info["url"]) == (
        "Piet de Vries", "CC BY-SA 4.0", "https://upload.example/thumb/1280px-B.jpg")


def _category_page(title, width=4000, height=3000, mime="image/jpeg", artist="Bob", assessed=""):
    meta = {"Artist": {"value": artist}, "LicenseShortName": {"value": "CC BY 4.0"}}
    if assessed:
        meta["Assessments"] = {"value": assessed}
    return {"title": title, "imageinfo": [{"mime": mime, "width": width, "height": height,
                                           "thumburl": f"https://upload.example/{title[5:]}", "extmetadata": meta}]}


def _commons_with_category(category):
    def fetch_json(url, params, **_):
        if params.get("titles"):  # de hoofdfoto uit Wikidata
            return {"query": {"pages": {"1": {"imageinfo": [{
                "mime": "image/jpeg", "thumburl": "https://upload.example/kerk.jpg",
                "extmetadata": {"Artist": {"value": "Anna"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}}}}
        assert params["gcmtitle"] == f"Category:{category}"
        pages = [
            _category_page("File:Zuidbroek kerk.jpg"),                         # dat is de hoofdfoto al
            _category_page("File:Zuidbroek straat.jpg"),
            _category_page("File:Zuidbroek molen.jpg", assessed="quality"),    # gekeurd: eerst
            _category_page("File:Kaart Zuidbroek.jpg"),                        # kaart
            _category_page("File:Wapen van Zuidbroek.jpg"),                    # wapen
            _category_page("File:Zuidbroek toren.jpg", width=2000, height=3000),  # staand
            _category_page("File:Zuidbroek klein.jpg", width=800, height=600),    # te klein
            _category_page("File:Zuidbroek oud.jpg", artist=""),                   # geen maker
            _category_page("File:Zuidbroek plan.svg", mime="image/svg+xml"),
        ]
        return {"query": {"pages": {str(i): page for i, page in enumerate(pages)}}}
    return fetch_json


def test_meer_fotos_uit_de_commons_categorie():
    item = {"file": "Zuidbroek kerk.jpg", "category": "Zuidbroek"}
    found = ep.commons_photos(item, _commons_with_category("Zuidbroek"))
    assert [p["file"] for p in found] == ["File:Zuidbroek kerk.jpg", "File:Zuidbroek molen.jpg", "File:Zuidbroek straat.jpg"]
    assert found[0]["author"] == "Anna" and found[2]["license"] == "CC BY 4.0"
    assert len(ep.commons_photos(item, _commons_with_category("Zuidbroek"), limit=2)) == 2


# ---------------------------------------------------------------- de nachtelijke ronde

def _raw(id_, title, url, city, venue=None, lat=None, lon=None):
    return {"id": id_, "title": title, "startDate": "2026-11-01", "city": city, "location": venue,
            "lat": lat, "lon": lon, "verificationStatus": "organizer_confirmed",
            "eventUrl": url, "sourceUrl": url, "sourceType": "event_official"}


def test_nachtelijke_ronde_vult_de_cache_en_onthoudt_alles(tmp_path):
    (tmp_path / "events.json").write_text(json.dumps([
        _raw("a", "Concert A", "https://melk.example/a", "Bunne", "De Melkfabriek", 53.13, 6.53),
        _raw("b", "Braderie", "https://dicht.example/b", "Groningen"),
        _raw("c", "Kermis", "https://leeg.example/c", "Zuidbroek", None, 53.16, 6.86),
    ]))
    pages = {
        "https://melk.example/robots.txt": (404, "text/plain", ""),
        "https://melk.example/a": (200, "text/html", '<html><meta property="og:image" content="/a.jpg"></html>'),
        "https://melk.example/": (200, "text/html", '<html><meta property="og:image" content="/huis.jpg"></html>'),
        "https://dicht.example/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /"),
        "https://leeg.example/robots.txt": (404, "text/plain", ""),
        "https://leeg.example/c": (200, "text/html", "<html><title>Kermis</title></html>"),
    }
    fetched = []

    def fetch(url, timeout=15):
        fetched.append(url)
        status, ctype, text = pages.get(url, (404, "text/html", ""))
        return Fetched(url, status, ctype, text)

    fetch_json, calls = _wiki(
        {"Zuidbroek": [{"id": "Q5", "label": "Zuidbroek", "description": "dorp in Midden-Groningen"}]},
        {"Q5": _entity(53.165, 6.86, "Zuidbroek kerk.jpg")},
        {"query": {"pages": {"1": {"imageinfo": [{"mime": "image/jpeg", "thumburl": "https://upload.example/z.jpg",
                                                  "descriptionurl": "https://commons.example/z",
                                                  "extmetadata": {"Artist": {"value": "Kees"},
                                                                  "LicenseShortName": {"value": "CC BY 3.0"}}}]}}}})
    cache_path = tmp_path / "photos.json"
    stats = ep.run(tmp_path, cache_path, today=TODAY, fetch=fetch, fetch_json=fetch_json, sleeper=lambda s: None)
    cache = json.loads(cache_path.read_text())

    assert cache["pages"]["https://melk.example/a"]["image"] == "https://melk.example/a.jpg"
    assert cache["pages"]["https://dicht.example/b"]["note"] == "robots.txt staat het niet toe"
    assert "https://dicht.example/b" not in fetched  # robots.txt gerespecteerd
    assert cache["homepages"]["melk.example"]["image"] == "https://melk.example/huis.jpg"
    assert cache["commons"]["plaats:zuidbroek"]["photos"][0]["author"] == "Kees"
    assert cache["commons"]["plaats:groningen"]["url"] is None
    assert stats["foto's van Wikimedia gevonden"] == 1

    # Tweede nacht: alles is onthouden, er wordt niets opnieuw opgehaald.
    fetched.clear()
    calls.clear()
    ep.run(tmp_path, cache_path, today=TODAY, fetch=fetch, fetch_json=fetch_json, sleeper=lambda s: None)
    assert fetched == [] and calls == []


def test_fabriek_zet_de_foto_bij_het_uitje_en_telt_ze(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    (data / "events.json").write_text(json.dumps([
        _raw("a", "Concert A", "https://melk.example/a", "Bunne", "De Melkfabriek", 53.13, 6.53),
        _raw("b", "Kermis", "https://x.example/b", "Bourtange", None, 53.01, 7.19),
        _raw("c", "Lezing", "https://y.example/c", "Haren", None, 53.17, 6.60),
    ]))
    events, status = build(data, out, TODAY, {}, photo_cache=CACHE, names={"melk.example": "De Melkfabriek"})
    by_title = {e["title"]: e for e in events}
    assert by_title["Concert A"]["image"]["credit"] == "Foto: De Melkfabriek"
    assert by_title["Kermis"]["image"]["match"] == "plaats"
    assert by_title["Lezing"]["image"] is None
    assert status["photos"] == {"organisator": 1, "wikimedia": 1, "zonder": 1}

    # Een nieuwe foto maakt een uitje niet 'gewijzigd': de vingerafdruk gaat over de feiten.
    again, _ = build(data, out, TODAY, {}, photo_cache={}, names={})
    assert [e["hash"] for e in again] == [e["hash"] for e in events]


def test_tijdelijke_storing_wacht_een_paar_dagen(tmp_path):
    (tmp_path / "events.json").write_text(json.dumps([_raw("a", "Concert", "https://stuk.example/a", "Bunne")]))

    def fetch(url, timeout=15):
        raise TimeoutError("geen antwoord")

    def fetch_json(url, params, **_):
        raise TimeoutError("geen antwoord")

    stats = ep.run(tmp_path, tmp_path / "photos.json", today=TODAY, fetch=fetch, fetch_json=fetch_json,
                   sleeper=lambda s: None)
    cache = json.loads((tmp_path / "photos.json").read_text())
    # Onthouden als 'tijdelijk': niet elke ronde opnieuw (dan gaan de 150 pagina's op aan dezelfde storingen),
    # maar over een paar dagen wel. Wikimedia blijft gewoon de volgende ronde opnieuw.
    page = cache["pages"]["https://stuk.example/a"]
    assert page["tijdelijk"] and not page["image"] and cache["commons"] == {}
    assert stats["tijdelijk onbereikbaar"] == 1 and stats["fouten bij Wikimedia"] == 1
    assert not ep._due(page, TODAY, ep.RECHECK_EMPTY_DAYS, "image")
    assert ep._due(page, TODAY + timedelta(days=ep.RECHECK_TEMPORARY_DAYS), ep.RECHECK_EMPTY_DAYS, "image")


def test_stopt_op_tijd_en_bewaart_wat_er_is(tmp_path):
    (tmp_path / "events.json").write_text(json.dumps(
        [_raw(str(i), f"Uitje {i}", f"https://traag.example/{i}", "Bunne") for i in range(5)]))
    now = [0.0]

    def fetch(url, timeout=15):
        now[0] += 100  # elke pagina duurt 100 seconden
        if url.endswith("robots.txt"):
            return Fetched(url, 404, "text/plain", "")
        return Fetched(url, 200, "text/html", "<html></html>")

    stats = ep.run(tmp_path, tmp_path / "photos.json", today=TODAY, fetch=fetch, fetch_json=lambda *a, **k: {},
                   sleeper=lambda s: None, clock=lambda: now[0], budget_seconds=250)
    cache = json.loads((tmp_path / "photos.json").read_text())
    assert stats["pagina's bekeken"] == 2 and len(cache["pages"]) == 2  # de rest volgende nacht


def test_oude_cache_met_een_foto_per_plaats_wordt_aangevuld(tmp_path):
    (tmp_path / "events.json").write_text(json.dumps([_raw("c", "Kermis", "https://leeg.example/c", "Zuidbroek", None, 53.16, 6.86)]))
    old = {"url": "https://upload.example/oud.jpg", "author": "Kees", "license": "CC BY 3.0", "checkedAt": "2026-10-01"}
    start = {"pages": {"https://leeg.example/c": {"image": None, "checkedAt": "2026-10-11"}}, "homepages": {},
             "commons": {"plaats:zuidbroek": old}}
    cache_path = tmp_path / "photos.json"

    # Wikidata vindt de plaats niet meer: de oude foto blijft staan.
    cache_path.write_text(json.dumps(start))
    ep.run(tmp_path, cache_path, today=TODAY, fetch=lambda *a, **k: None, fetch_json=_wiki({}, {})[0], sleeper=lambda s: None)
    entry = json.loads(cache_path.read_text())["commons"]["plaats:zuidbroek"]
    assert [p["url"] for p in entry["photos"]] == ["https://upload.example/oud.jpg"]

    # Wel gevonden: de plaats krijgt meer foto's, één keer.
    cache_path.write_text(json.dumps(start))
    entity = _entity(53.165, 6.86, "Zuidbroek kerk.jpg")
    entity["claims"]["P373"] = [{"mainsnak": {"datavalue": {"value": "Zuidbroek"}}, "rank": "normal"}]
    search, _ = _wiki({"Zuidbroek": [{"id": "Q5", "label": "Zuidbroek", "description": "dorp in Midden-Groningen"}]},
                      {"Q5": entity})
    commons = _commons_with_category("Zuidbroek")
    calls = []

    def fetch_json(url, params, **kw):
        calls.append(params["action"])
        return search(url, params) if params["action"].startswith("wb") else commons(url, params)

    stats = ep.run(tmp_path, cache_path, today=TODAY, fetch=lambda *a, **k: None, fetch_json=fetch_json, sleeper=lambda s: None)
    entry = json.loads(cache_path.read_text())["commons"]["plaats:zuidbroek"]
    assert len(entry["photos"]) == 3 and entry["url"] == "https://upload.example/kerk.jpg" and entry["wikidata"] == "Q5"
    assert stats["foto's van Wikimedia gevonden"] == 3
    calls.clear()
    ep.run(tmp_path, cache_path, today=TODAY, fetch=lambda *a, **k: None, fetch_json=fetch_json, sleeper=lambda s: None)
    assert calls == []


def test_door_ai_gemaakt_plaatje_is_geen_foto_ook_niet_uit_de_bewaarde_lijst():
    from collector.event_photos import usable_image
    from pipeline.v2.photos import choose_photo
    page = "https://www.ervaarharen.nl/event/lichtjesparade/"
    ai = "https://www.ervaarharen.nl/wp-content/uploads/2026/09/ChatGPT-Image-9-sep-2026-14_56_52-1024x768.png"
    assert usable_image(ai, page) is None
    cache = {"pages": {page: {"image": ai}}, "homepages": {"ervaarharen.nl": {"image": None}}}
    event = {"title": "Lichtjesparade Haren", "url": page,
             "sources": [{"type": "organisator", "url": page, "host": "ervaarharen.nl"}],
             "venue": {"city": "Haren"}}
    photo = choose_photo(event, cache, lists=set(), names={})
    assert photo is None or photo.get("type") != "organisator"


def test_geen_verwijzing_stockfoto_of_miniatuur_als_foto():
    """Nakijken van de foto's (oktober 2026): Yoast '#primaryimage' is een verwijzing, geen foto; stockfoto's,
    kaartjes en miniaturen zijn geen foto van het uitje."""
    from collector.event_photos import usable_image
    page = "https://appelscha.nl/tstevent/markt/"
    for bad in ("https://appelscha.nl/tstevent/markt/#primaryimage", "https://x.nl/maan-pixabay.jpg",
                "https://x.nl/uploads/foto-150x150.jpg", "https://x.nl/ticket_1_eersterang.png", "https://x.nl/images.png",
                "https://x.nl/img.jpg?width=200"):
        assert usable_image(bad, page) is None, bad
    for good in ("https://x.nl/uploads/concert-1024x683.jpg", "https://x.nl/img.jpg?w=1200"):
        assert usable_image(good, page) == good
