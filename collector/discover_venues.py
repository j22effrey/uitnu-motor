"""Bronnenmachine: vind zelf alle plekken en festivals met een eigen website.

Waar het zoekt:
- OpenStreetMap (Overpass): podia, theaters, bioscopen, dorpshuizen, musea, kerken,
  sportcentra, clubs, cafés, verenigingen, gemeentehuizen en andere plekken met een website,
  en dorpen en wijken met een eigen dorpswebsite, binnen het werkgebied.
- Wikidata: festivals in Groningen, Drenthe en Friesland met een officiële website, en
  dorpen, steden en gemeenten in het werkgebied met een officiële website.
- Tips van de eigenaar (collector/tips.json): websites die de robot zelf niet vond.
- Dorpswebsites (data/dorpssites.json): per plaats gezocht en gecontroleerd door
  collector/village_sites.py.

Wat het oplevert: websites in de bestaande bronwachtrij (data/source_candidates.json).
Een kandidaat is nog geen bron. De bestaande probe (collector/source_probe.py) kijkt daarna
of de site een agenda met schema.org, iCal of WordPress-events heeft, en jij keurt goed.

Andere agenda's en verzamelsites worden bewust overgeslagen: UITNU haalt alles bij de bron.

Licenties: OpenStreetMap-data valt onder de ODbL (naamsvermelding verplicht),
Wikidata-data onder CC0.

Draaien:  python -m collector.discover_venues --queue data/source_candidates.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from collector.source_candidates import filter_new_hosts, host_key, load_source_hosts, update_queue
from pipeline import area

USER_AGENT = "UITNU-bronnenmachine/1.0 (+https://uitnu.pages.dev/over/)"
# OpenStreetMap: de hoofdserver, en twee andere openbare servers als die het te druk heeft.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
OVERPASS_URL = OVERPASS_URLS[0]
WIKIDATA_URL = "https://query.wikidata.org/sparql"
# Wikidata zelf, en anders een snelle kopie (QLever, Universiteit van Freiburg; net als village_sites).
SPARQL_ENDPOINTS = (WIKIDATA_URL, "https://qlever.dev/api/wikidata")
# Zoeken mag samen hooguit zoveel minuten duren (de stap in de motor stopt na 20).
SEARCH_BUDGET_SECONDS = 15 * 60

# Het werkgebied staat in pipeline/area.py (een lijstje provincies). Sommige zoekdiensten kennen alleen
# een cirkel: dan zoeken we in een cirkel om het hele gebied en houden we alleen wat erin ligt.
AREA_CENTER = area.center()
AREA_RADIUS_KM = round(area.radius_km())

# Soort plek -> startscore. Plekken die vaak een eigen agenda hebben scoren hoger.
OSM_TYPES: dict[tuple[str, str], int] = {
    ("amenity", "theatre"): 30,
    ("amenity", "arts_centre"): 30,
    ("amenity", "music_venue"): 30,
    ("amenity", "events_venue"): 30,
    ("amenity", "cinema"): 25,
    ("amenity", "nightclub"): 20,
    ("amenity", "community_centre"): 20,
    ("amenity", "social_centre"): 15,
    ("amenity", "library"): 15,
    ("amenity", "place_of_worship"): 10,
    ("tourism", "museum"): 25,
    ("tourism", "gallery"): 20,
    ("tourism", "attraction"): 10,
    ("tourism", "zoo"): 15,
    ("tourism", "theme_park"): 15,
    ("leisure", "sports_centre"): 15,
    ("leisure", "stadium"): 15,
    ("leisure", "nature_reserve"): 10,
    ("leisure", "marina"): 10,
    ("historic", "castle"): 15,          # borgen en kastelen met activiteiten
    ("historic", "manor"): 15,
    ("amenity", "townhall"): 15,         # gemeente: mag als bron (vaste regel 1)
    ("office", "association"): 12,       # verenigingen en stichtingen, zoals dorpsbelangen
    ("amenity", "pub"): 8,               # cafés met live muziek
    ("amenity", "bar"): 8,
    # Dorpen en wijken met een eigen website: daar staan vaak de dorpsactiviteiten.
    ("place", "village"): 25,
    ("place", "hamlet"): 20,
    ("place", "town"): 20,
    ("place", "suburb"): 15,
    ("place", "neighbourhood"): 15,
    ("place", "city"): 10,
}

# Nooit als bron: andere agenda's, verzamelsites, media en sociale netwerken.
EXCLUDED_HOSTS = {
    "visitgroningen.nl", "kultuuragenda.nl", "wattedoenin.nl", "insidegroningen.com",
    "uitagenda.nl", "uitinnederland.nl", "uitzinnig.nl", "eventbrite.nl", "eventbrite.com",
    "dvhn.nl", "rtvnoord.nl", "oogtv.nl", "groningerinternetcourant.nl",
    "zeijen.nu", "ruinerwold.info", "liwwadders.nl",   # dorpsnieuws: berichten, geen agenda van een organisator
    "facebook.com", "m.facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "tiktok.com", "linktr.ee", "wikipedia.org", "nl.wikipedia.org",
    "google.com", "google.nl", "sites.google.com",
    # wiki's, universiteiten en boekingssites zijn geen agenda van een plek of organisator
    "reliwiki.nl", "wikidata.org", "wikimedia.org", "rug.nl", "hanze.nl",
    "museen.de",   # Duits museumportaal: een verzamelsite, niet de website van het museum zelf
    "tripadvisor.nl", "tripadvisor.com", "booking.com",
    # landelijke overheid: hun 'activiteiten' gaan over het hele land, niet over deze plek
    "defensie.nl", "rijksoverheid.nl", "overheid.nl", "government.nl",
}
TIPS_PATH = "collector/tips.json"
VILLAGE_SITES_PATH = "data/dorpssites.json"
# Naast de wachtrij: wanneer elke zoekbron voor het laatst lukte, en voor welk werkgebied.
SEARCH_LOG_NAME = "zoekronde.json"
WIKIDATA_SEARCHES = ("Wikidata (festivals)", "Wikidata (dorpen en gemeenten)")


def search_names(provinces: tuple[str, ...] = area.AREA_PROVINCES) -> list[str]:
    """De zoekbronnen: OpenStreetMap per provincie (een kleinere vraag lukt vaker), en Wikidata."""
    return [f"OpenStreetMap ({province})" for province in provinces] + list(WIKIDATA_SEARCHES)


def overpass_query(provinces: tuple[str, ...] = area.AREA_PROVINCES) -> str:
    """Overpass QL: alle plekken van de soorten hierboven met een website-tag, in de provincies van
    het werkgebied (OpenStreetMap kent ze aan hun ISO-code, zoals NL-GR). Eén regel per sleutel
    (amenity, tourism, ...) met alle waarden erin: dat is lichter voor de server."""
    codes = "|".join(area.iso_codes(tuple(provinces)))
    values: dict[str, list[str]] = {}
    for key, value in OSM_TYPES:
        values.setdefault(key, []).append(value)
    # Eerst alles met een website in het gebied (snel via de index), daarna pas op soort filteren.
    lines = [f'  nwr.sites["{key}"~"^({"|".join(names)})$"];' for key, names in values.items()]
    lines.append('  nwr.sites["club"];')
    return ("[out:json][timeout:180];\n"
            f'area["ISO3166-2"~"^({codes})$"]->.werkgebied;\n'
            '(nwr["website"](area.werkgebied); nwr["contact:website"](area.werkgebied);)->.sites;\n'
            "(\n" + "\n".join(lines) + "\n);\nout center tags;")


# Gewone SPARQL (geen extra's van Wikidata zelf), zodat ook het reserve-adres werkt. Namen: Nederlands,
# anders Fries, anders Engels (zie wikidata_label).
WIKIDATA_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?item ?nl ?fy ?en ?website ?region ?coord ?placeCoord WHERE {
  VALUES ?region { %s }   # de provincies van het werkgebied
  ?item wdt:P31/wdt:P279* wd:Q132241 .          # een festival (of een soort festival)
  ?item wdt:P131* ?region .
  ?item wdt:P856 ?website .
  OPTIONAL { ?item wdt:P625 ?coord . }
  OPTIONAL { ?item wdt:P276 ?place . ?place wdt:P625 ?placeCoord . }
  OPTIONAL { ?item rdfs:label ?nl . FILTER(LANG(?nl) = "nl") }
  OPTIONAL { ?item rdfs:label ?fy . FILTER(LANG(?fy) = "fy") }
  OPTIONAL { ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }
}
LIMIT 2000
"""


# Woonplaatsen en gemeenten van het land met een officiële website; het werkgebied wordt daarna
# uitgeknipt (pipeline/area.py). Een cirkel om het hele gebied was te zwaar voor Wikidata.
WIKIDATA_PLACES_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?item ?nl ?fy ?en ?website ?coord ?type WHERE {
  ?item wdt:P17 wd:Q55 ; wdt:P31 ?type ; wdt:P856 ?website ; wdt:P625 ?coord .
  VALUES ?type { wd:Q532 wd:Q3957 wd:Q5084 wd:Q486972 wd:Q1852859 wd:Q2039348 wd:Q15284 wd:Q1549591 wd:Q515 }
  OPTIONAL { ?item rdfs:label ?nl . FILTER(LANG(?nl) = "nl") }
  OPTIONAL { ?item rdfs:label ?fy . FILTER(LANG(?fy) = "fy") }
  OPTIONAL { ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }
}
"""
MUNICIPALITY = "Q2039348"


def normalize_website(value: str | None) -> str | None:
    """'www.dorpshuis.nl' -> 'https://www.dorpshuis.nl/'; lege of rare waarden -> None."""
    value = (value or "").strip().split(";")[0].strip()
    if not value or " " in value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    if not parsed.hostname or "." not in parsed.hostname:
        return None
    path = parsed.path or "/"
    return urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def is_excluded(url: str) -> bool:
    host = host_key(url)
    return any(host == bad or host.endswith("." + bad) for bad in EXCLUDED_HOSTS)


def discoveries_from_overpass(payload: dict) -> list[dict]:
    found: list[dict] = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        url = normalize_website(tags.get("website") or tags.get("contact:website"))
        if not url or is_excluded(url):
            continue
        score, label = 10, "club"
        for (key, value), points in OSM_TYPES.items():
            if tags.get(key) == value:
                score, label = points, value
                break
        lat = element.get("lat", (element.get("center") or {}).get("lat"))
        lon = element.get("lon", (element.get("center") or {}).get("lon"))
        name = tags.get("name") or "naamloze plek"
        # Een dorp of wijk is zelf de plaats ('Froombosch (village, Froombosch)').
        place = tags.get("addr:city") or tags.get("addr:place") or (name if tags.get("place") and tags.get("name") else "")
        kind = element.get("type", "node")
        found.append({
            "url": url,
            "score": score,
            "kind": "osm",
            "source_id": f"osm:{kind}/{element.get('id')}",
            "from_url": f"https://www.openstreetmap.org/{kind}/{element.get('id')}",
            "anchor_text": f"{name} ({label}{', ' + place if place else ''})",
            "lat": lat,
            "lon": lon,
        })
    return found


def wikidata_label(row: dict) -> str | None:
    """De naam uit Wikidata: Nederlands, anders Fries, anders Engels. Zonder naam gaf Wikidata soms de
    code terug ('Q1977146'): dat is geen naam, en zeker geen plaatsnaam."""
    for key in ("nl", "fy", "en", "itemLabel"):
        label = str((row.get(key) or {}).get("value") or "").strip()
        if label and not re.fullmatch(r"Q\d+", label):
            return label
    return None


def discoveries_from_wikidata(payload: dict) -> list[dict]:
    found: list[dict] = []
    for row in payload.get("results", {}).get("bindings", []):
        url = normalize_website(row.get("website", {}).get("value"))
        if not url or is_excluded(url):
            continue
        entity = row.get("item", {}).get("value", "")
        qid = entity.rsplit("/", 1)[-1]
        point = (row.get("coord") or row.get("placeCoord") or {}).get("value", "")
        match = re.match(r"Point\(([-0-9.]+) ([-0-9.]+)\)", point, re.I)
        found.append({
            "url": url,
            "score": 35,
            "kind": "wikidata",
            "source_id": f"wikidata:{qid}",
            "from_url": entity,
            "anchor_text": f"{wikidata_label(row)} (festival)" if wikidata_label(row) else None,
            "lat": float(match.group(2)) if match else None,
            "lon": float(match.group(1)) if match else None,
            "region": row.get("region", {}).get("value", "").rsplit("/", 1)[-1],
        })
    return found


def discoveries_from_wikidata_places(payload: dict) -> list[dict]:
    found: list[dict] = []
    for row in payload.get("results", {}).get("bindings", []):
        url = normalize_website(row.get("website", {}).get("value"))
        if not url or is_excluded(url):
            continue
        entity = row.get("item", {}).get("value", "")
        qid = entity.rsplit("/", 1)[-1]
        match = re.match(r"Point\(([-0-9.]+) ([-0-9.]+)\)", row.get("coord", {}).get("value", ""), re.I)
        if not match or not area.in_area(float(match.group(2)), float(match.group(1))):
            continue  # de vraag gaat over het hele land: alleen het werkgebied houden
        municipality = row.get("type", {}).get("value", "").endswith("/" + MUNICIPALITY)
        found.append({
            "url": url,
            "score": 20 if municipality else 25,
            "kind": "wikidata",
            "source_id": f"wikidata:{qid}",
            "from_url": entity,
            "anchor_text": (f"{wikidata_label(row)} ({'gemeente' if municipality else 'dorp'})"
                            if wikidata_label(row) else None),
            "lat": float(match.group(2)),
            "lon": float(match.group(1)),
        })
    return found


def discoveries_from_tips(path: str | Path) -> list[dict]:
    """Websites die de eigenaar zelf aandraagt (bijvoorbeeld een dorpswebsite met een uitje dat
    ontbrak). Ze krijgen voorrang bij het testen en gelden als 'in het werkgebied'."""
    path = Path(path)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    found = []
    for tip in payload.get("tips", []) if isinstance(payload, dict) else []:
        url = normalize_website((tip or {}).get("url"))
        if not url or is_excluded(url):
            continue
        place = str(tip.get("plaats") or "").strip()
        found.append({
            "url": url,
            "score": 60,
            "kind": "tip",
            "source_id": f"tip:{host_key(url)}",
            "from_url": None,
            "anchor_text": f"{tip.get('naam') or host_key(url)} (tip{', ' + place if place else ''})",
            "lat": tip.get("lat"),
            "lon": tip.get("lon"),
        })
    return found


def discoveries_from_village_sites(path: str | Path) -> list[dict]:
    """Dorpswebsites die collector/village_sites.py per plaats heeft gevonden en goedgekeurd.
    Alleen het oordeel 'dorpssite'; twijfelgevallen niet (die eerst nakijken)."""
    path = Path(path)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    found = []
    for qid, place in (payload.get("plaatsen") or {}).items() if isinstance(payload, dict) else []:
        for site in (place or {}).get("sites") or []:
            url = normalize_website((site or {}).get("url"))
            if site.get("oordeel") != "dorpssite" or not url or is_excluded(url):
                continue
            name = re.sub(r"[()]", "", str(site.get("naam") or host_key(url))).strip()
            found.append({
                "url": url,
                "score": 45,
                "kind": "dorpssite",
                "source_id": f"dorpssite:{qid}",
                "from_url": f"https://www.wikidata.org/wiki/{qid}",
                "anchor_text": f"{name} (dorpssite, {place.get('naam')})",
                "lat": place.get("lat"),
                "lon": place.get("lon"),
            })
    return found


def distance_km(lat: float, lon: float, center: tuple[float, float] = AREA_CENTER) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat - center[0]), radians(lon - center[1])
    a = sin(dlat / 2) ** 2 + cos(radians(center[0])) * cos(radians(lat)) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def area_of(discovery: dict) -> tuple[str, float | None]:
    """'binnen', 'buiten' of 'onbekend' (werkgebied: pipeline/area.py), met de afstand tot het midden
    van het werkgebied als die bekend is."""
    if discovery.get("kind") == "tip" and discovery.get("lat") is None:
        return "binnen", None
    if discovery.get("lat") is not None and discovery.get("lon") is not None:
        lat, lon = float(discovery["lat"]), float(discovery["lon"])
        km = round(distance_km(lat, lon), 1)
        return ("binnen" if area.in_area(lat, lon) else "buiten"), km
    if discovery.get("region") in area.wikidata_ids():
        return "binnen", None
    return "onbekend", None


AREA_NOTE = "buiten het werkgebied"


def annotate_area(queue_path: str, discoveries: list[dict]) -> dict:
    """Schrijf bij elke kandidaat of hij in het werkgebied ligt. Buiten het gebied wordt niet getest.
    Kijkt ook naar wat er al in de wachtrij staat (met de plekken van eerder): na een groter werkgebied
    komen websites die eerst buiten lagen vanzelf weer aan de beurt."""
    best: dict[str, tuple[str, float | None]] = {}
    rank = {"binnen": 0, "onbekend": 1, "buiten": 2}
    path = Path(queue_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    known: list[dict] = []
    for item in payload.get("candidates", []):
        url = item.get("url") or f"https://{item.get('host')}/"
        evidence = [e for e in item.get("evidence") or [] if isinstance(e, dict)]
        points = [e for e in evidence if e.get("lat") is not None and e.get("lon") is not None]
        known += [{"url": url, "lat": e["lat"], "lon": e["lon"]} for e in points]
        if not points and any(e.get("kind") == "tip" for e in evidence):
            known.append({"url": url, "kind": "tip"})
    for discovery in [*discoveries, *known]:
        host = host_key(discovery["url"])
        status, km = area_of(discovery)
        if host not in best or rank[status] < rank[best[host][0]] or (
                status == best[host][0] and km is not None and (best[host][1] is None or km < best[host][1])):
            best[host] = (status, km)
    counts = {"binnen": 0, "onbekend": 0, "buiten": 0}
    for item in payload.get("candidates", []):
        host = item.get("host") or host_key(item.get("url") or "")
        if host not in best:
            continue
        status, km = best[host]
        item["areaStatus"], item["distanceKm"] = status, km
        counts[status] += 1
        if status == "buiten" and item.get("activationStatus") in (None, "candidate"):
            item["policyStatus"] = "blocked"
            item["policyNote"] = f"{AREA_NOTE} ({area.AREA_LABEL})"
        elif status != "buiten" and item.get("policyStatus") == "blocked" \
                and str(item.get("policyNote") or "").startswith(AREA_NOTE):
            # Eerst buiten het werkgebied, nu erbinnen: weer gewoon in de wachtrij.
            item["policyStatus"] = "review"
            item.pop("policyNote", None)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return counts


def _fetch_json(url: str, data: bytes | None = None, timeout: int = 150) -> dict:
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/sparql-results+json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _first_that_works(urls: tuple[str, ...], body: bytes, timeout: int) -> dict:
    """Vraag het de eerste server; lukt dat niet (druk, storing), dan de volgende."""
    problems = []
    for url in urls:
        try:
            return _fetch_json(url, data=body, timeout=timeout)
        except Exception as error:
            problems.append(f"{urllib.parse.urlparse(url).hostname}: {error}")
    raise RuntimeError("; ".join(problems))


def _overpass_answer(payload: dict) -> dict:
    """Een server die te druk is, geeft soms een leeg antwoord met een opmerking ('runtime error:
    Query timed out'). Dat is geen uitkomst (anders denkt de motor dat er niets te vinden was)."""
    remark = str(payload.get("remark") or "")
    if re.search(r"error|timed out|timeout|out of memory", remark, re.I):
        raise RuntimeError(f"Overpass: {remark[:120]}")
    return payload


def fetch_overpass(provinces: tuple[str, ...] = area.AREA_PROVINCES) -> dict:
    body = urllib.parse.urlencode({"data": overpass_query(provinces)}).encode("utf-8")
    problems = []
    for url in OVERPASS_URLS:
        try:
            return _overpass_answer(_fetch_json(url, data=body, timeout=200))
        except Exception as error:
            problems.append(f"{urllib.parse.urlparse(url).hostname}: {error}")
    raise RuntimeError("; ".join(problems))


def wikidata_query() -> str:
    return WIKIDATA_QUERY % " ".join(f"wd:{qid}" for qid in area.wikidata_ids())


def fetch_wikidata() -> dict:
    body = urllib.parse.urlencode({"query": wikidata_query(), "format": "json"}).encode("utf-8")
    return _first_that_works(SPARQL_ENDPOINTS, body, timeout=150)


def fetch_wikidata_places() -> dict:
    body = urllib.parse.urlencode({"query": WIKIDATA_PLACES_QUERY, "format": "json"}).encode("utf-8")
    return _first_that_works(SPARQL_ENDPOINTS, body, timeout=150)


def searches_due(log: dict, every_days: int | None, today: date) -> list[str]:
    """Welke zoekbronnen aan de beurt zijn. Zonder every_days: allemaal. Anders alleen een bron die
    every_days of meer dagen geleden voor het laatst lukte (of nog nooit), en allemaal als het
    werkgebied sindsdien is veranderd."""
    if not every_days or log.get("werkgebied") != list(area.AREA_PROVINCES):
        return search_names()
    due = []
    for name in search_names():
        try:
            age = (today - date.fromisoformat(str((log.get("gelukt") or {}).get(name)))).days
        except ValueError:
            age = None
        if age is None or age >= every_days:
            due.append(name)
    return due


def _read_log(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_search_log(path: Path, log: dict, done: list[str], today: date) -> dict:
    """Onthoud welke zoekbronnen vandaag lukten. Een nieuw werkgebied begint met een schone lei."""
    if log.get("werkgebied") != list(area.AREA_PROVINCES):
        log = {"werkgebied": list(area.AREA_PROVINCES), "gelukt": {}}
    log.setdefault("gelukt", {}).update({name: today.isoformat() for name in done})
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UITNU bronnenmachine")
    parser.add_argument("--queue", default="data/source_candidates.json")
    parser.add_argument("--known", default="collector/web_crawl_sources.json",
                        help="bronnen die al actief zijn en niet opnieuw in de wachtrij hoeven")
    parser.add_argument("--osm-json", help="eerder opgeslagen Overpass-antwoord (voor testen)")
    parser.add_argument("--wikidata-json", help="eerder opgeslagen Wikidata-antwoord (voor testen)")
    parser.add_argument("--places-json", help="eerder opgeslagen Wikidata-antwoord met woonplaatsen (voor testen)")
    parser.add_argument("--tips", default=TIPS_PATH, help="websites die de eigenaar aandraagt")
    parser.add_argument("--village-sites", default=VILLAGE_SITES_PATH,
                        help="dorpswebsites gevonden door collector/village_sites.py")
    parser.add_argument("--tips-only", action="store_true",
                        help="alleen de tips en gevonden dorpswebsites toevoegen (geen internet nodig)")
    parser.add_argument("--dry-run", action="store_true", help="alleen tellen, wachtrij niet aanpassen")
    parser.add_argument("--every-days", type=int, default=None,
                        help="een zoekbron alleen opnieuw vragen als die zoveel dagen geleden voor het laatst lukte")
    parser.add_argument("--search-log", help=f"waar dat wordt onthouden (standaard {SEARCH_LOG_NAME} naast de wachtrij)")
    args = parser.parse_args(argv)

    discoveries: list[dict] = discoveries_from_tips(args.tips) + discoveries_from_village_sites(args.village_sites)
    problems: list[str] = []
    log_path = Path(args.search_log) if args.search_log else Path(args.queue).with_name(SEARCH_LOG_NAME)
    log = _read_log(log_path)
    due = [] if args.tips_only else searches_due(log, args.every_days, date.today())
    if not args.tips_only and not due:
        print(f"Nieuwe plekken zoeken: niet nodig, de vorige keer is minder dan {args.every_days} dagen geleden.")
    done: list[str] = []
    started = time.monotonic()
    osm_due = [name for name in due if name.startswith("OpenStreetMap")]
    if args.osm_json and osm_due:
        try:
            discoveries += discoveries_from_overpass(json.loads(Path(args.osm_json).read_text(encoding="utf-8")))
            done += osm_due
        except Exception as error:
            problems.append(f"OpenStreetMap: {error}")
    elif osm_due:
        for province in area.AREA_PROVINCES:
            name = f"OpenStreetMap ({province})"
            if name not in osm_due:
                continue
            if time.monotonic() - started > SEARCH_BUDGET_SECONDS:
                problems.append(f"{name}: geen tijd meer, de volgende ronde verder")
                continue
            try:  # een bron die faalt mag de andere niet tegenhouden
                discoveries += discoveries_from_overpass(fetch_overpass((province,)))
                done.append(name)
            except Exception as error:
                problems.append(f"{name}: {error}")
    if "Wikidata (festivals)" in due:
        try:
            wiki = json.loads(Path(args.wikidata_json).read_text(encoding="utf-8")) if args.wikidata_json else fetch_wikidata()
            discoveries += discoveries_from_wikidata(wiki)
            done.append("Wikidata (festivals)")
        except Exception as error:
            problems.append(f"Wikidata (festivals): {error}")
    if "Wikidata (dorpen en gemeenten)" in due:
        try:
            places = (json.loads(Path(args.places_json).read_text(encoding="utf-8")) if args.places_json
                      else fetch_wikidata_places())
            discoveries += discoveries_from_wikidata_places(places)
            done.append("Wikidata (dorpen en gemeenten)")
        except Exception as error:
            problems.append(f"Wikidata (dorpen en gemeenten): {error}")

    new = filter_new_hosts(discoveries, load_source_hosts(args.known))
    hosts = {host_key(d["url"]) for d in new}
    print(f"Gevonden: {len(discoveries)} plekken met website, {len(hosts)} nieuwe websites.")
    for problem in problems:
        print(f"Let op, niet gelukt: {problem}")
    if not args.dry_run and new:
        queue = update_queue(args.queue, new)
        print(f"Wachtrij bijgewerkt: {len(queue)} kandidaten in {args.queue}.")
    if not args.dry_run and Path(args.queue).exists():
        counts = annotate_area(args.queue, discoveries)
        print(f"Werkgebied: {counts['binnen']} binnen, {counts['buiten']} buiten (worden niet getest), {counts['onbekend']} onbekend.")
    if done and not args.dry_run:
        save_search_log(log_path, log, done, date.today())
    return 1 if problems and not discoveries else 0


if __name__ == "__main__":
    raise SystemExit(main())
