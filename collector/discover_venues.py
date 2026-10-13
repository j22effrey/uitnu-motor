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
import urllib.parse
import urllib.request
from pathlib import Path

from collector.source_candidates import filter_new_hosts, host_key, load_source_hosts, update_queue
from pipeline import area

USER_AGENT = "UITNU-bronnenmachine/1.0 (+https://uitnu.pages.dev/over/)"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WIKIDATA_URL = "https://query.wikidata.org/sparql"

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


def overpass_query(provinces: tuple[str, ...] = area.AREA_PROVINCES) -> str:
    """Overpass QL: alle plekken van de soorten hierboven met een website-tag, in de provincies van
    het werkgebied (OpenStreetMap kent ze aan hun ISO-code, zoals NL-GR)."""
    codes = "|".join(area.iso_codes(tuple(provinces)))
    inside = "(area.werkgebied)"
    lines = []
    for (key, value), _ in OSM_TYPES.items():
        for site_key in ("website", "contact:website"):
            lines.append(f'  nwr["{key}"="{value}"]["{site_key}"]{inside};')
    lines.append(f'  nwr["club"]["website"]{inside};')
    return ("[out:json][timeout:240];\n"
            f'area["ISO3166-2"~"^({codes})$"]->.werkgebied;\n(\n' + "\n".join(lines) + "\n);\nout center tags;")


WIKIDATA_QUERY = """
SELECT DISTINCT ?item ?itemLabel ?website ?region ?coord ?placeCoord WHERE {
  VALUES ?region { %s }   # de provincies van het werkgebied
  ?item wdt:P31/wdt:P279* wd:Q132241 .          # een festival (of een soort festival)
  ?item wdt:P131* ?region .
  ?item wdt:P856 ?website .
  OPTIONAL { ?item wdt:P625 ?coord . }
  OPTIONAL { ?item wdt:P276 ?place . ?place wdt:P625 ?placeCoord . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "nl,en". }
}
LIMIT 2000
"""


# Woonplaatsen en gemeenten in het werkgebied met een officiële website (dorpswebsites).
WIKIDATA_PLACES_QUERY = """
SELECT DISTINCT ?item ?itemLabel ?website ?coord ?type WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{radius}" .
  }}
  ?item wdt:P31 ?type .
  VALUES ?type {{ wd:Q532 wd:Q3957 wd:Q5084 wd:Q486972 wd:Q1852859 wd:Q2039348 wd:Q15284 wd:Q1549591 wd:Q515 }}
  ?item wdt:P856 ?website .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nl,en". }}
}}
LIMIT 3000
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


def discoveries_from_wikidata(payload: dict) -> list[dict]:
    found: list[dict] = []
    for row in payload.get("results", {}).get("bindings", []):
        url = normalize_website(row.get("website", {}).get("value"))
        if not url or is_excluded(url):
            continue
        entity = row.get("item", {}).get("value", "")
        qid = entity.rsplit("/", 1)[-1]
        point = (row.get("coord") or row.get("placeCoord") or {}).get("value", "")
        match = re.match(r"Point\(([-0-9.]+) ([-0-9.]+)\)", point)
        found.append({
            "url": url,
            "score": 35,
            "kind": "wikidata",
            "source_id": f"wikidata:{qid}",
            "from_url": entity,
            "anchor_text": f"{row.get('itemLabel', {}).get('value', qid)} (festival)",
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
        match = re.match(r"Point\(([-0-9.]+) ([-0-9.]+)\)", row.get("coord", {}).get("value", ""))
        municipality = row.get("type", {}).get("value", "").endswith("/" + MUNICIPALITY)
        found.append({
            "url": url,
            "score": 20 if municipality else 25,
            "kind": "wikidata",
            "source_id": f"wikidata:{qid}",
            "from_url": entity,
            "anchor_text": f"{row.get('itemLabel', {}).get('value', qid)} ({'gemeente' if municipality else 'dorp'})",
            "lat": float(match.group(2)) if match else None,
            "lon": float(match.group(1)) if match else None,
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


def fetch_overpass() -> dict:
    body = urllib.parse.urlencode({"data": overpass_query()}).encode("utf-8")
    # Drie provincies vragen is zwaarder dan een cirkel van 60 km: ruim de tijd nemen.
    return _fetch_json(OVERPASS_URL, data=body, timeout=300)


def wikidata_query() -> str:
    return WIKIDATA_QUERY % " ".join(f"wd:{qid}" for qid in area.wikidata_ids())


def fetch_wikidata() -> dict:
    query = urllib.parse.urlencode({"query": wikidata_query(), "format": "json"})
    return _fetch_json(f"{WIKIDATA_URL}?{query}")


def fetch_wikidata_places() -> dict:
    # Een cirkel om het hele werkgebied; wat erbuiten valt, wordt daarna 'buiten' (annotate_area).
    sparql = WIKIDATA_PLACES_QUERY.format(lat=AREA_CENTER[0], lon=AREA_CENTER[1], radius=AREA_RADIUS_KM)
    query = urllib.parse.urlencode({"query": sparql, "format": "json"})
    return _fetch_json(f"{WIKIDATA_URL}?{query}")


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
    args = parser.parse_args(argv)

    discoveries: list[dict] = discoveries_from_tips(args.tips) + discoveries_from_village_sites(args.village_sites)
    problems: list[str] = []
    if not args.tips_only:
        try:
            osm = json.loads(Path(args.osm_json).read_text(encoding="utf-8")) if args.osm_json else fetch_overpass()
            discoveries += discoveries_from_overpass(osm)
        except Exception as error:  # een bron die faalt mag de andere niet tegenhouden
            problems.append(f"OpenStreetMap: {error}")
        try:
            wiki = json.loads(Path(args.wikidata_json).read_text(encoding="utf-8")) if args.wikidata_json else fetch_wikidata()
            discoveries += discoveries_from_wikidata(wiki)
        except Exception as error:
            problems.append(f"Wikidata (festivals): {error}")
        try:
            places = (json.loads(Path(args.places_json).read_text(encoding="utf-8")) if args.places_json
                      else fetch_wikidata_places())
            discoveries += discoveries_from_wikidata_places(places)
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
    return 1 if problems and not discoveries else 0


if __name__ == "__main__":
    raise SystemExit(main())
