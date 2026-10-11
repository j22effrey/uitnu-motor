"""Bronnenmachine: vind zelf alle plekken en festivals met een eigen website.

Waar het zoekt:
- OpenStreetMap (Overpass): podia, theaters, bioscopen, dorpshuizen, musea, kerken,
  sportcentra, clubs en andere plekken met een website, binnen het werkgebied.
- Wikidata: festivals in Groningen, Drenthe en Friesland met een officiële website.

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

USER_AGENT = "UITNU-bronnenmachine/1.0 (+https://uitnu.pages.dev/over/)"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WIKIDATA_URL = "https://query.wikidata.org/sparql"

AREA_CENTER = (53.2194, 6.5665)  # Groningen-centrum, gelijk aan de fabriek
AREA_RADIUS_KM = 60

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
    "tripadvisor.nl", "tripadvisor.com", "booking.com",
}
GRONINGEN_PROVINCE = "Q752"


def overpass_query(radius_km: int = AREA_RADIUS_KM, center: tuple[float, float] = AREA_CENTER) -> str:
    """Overpass QL: alle plekken van de soorten hierboven met een website-tag."""
    around = f"(around:{radius_km * 1000},{center[0]},{center[1]})"
    lines = []
    for (key, value), _ in OSM_TYPES.items():
        for site_key in ("website", "contact:website"):
            lines.append(f'  nwr["{key}"="{value}"]["{site_key}"]{around};')
    lines.append(f'  nwr["club"]["website"]{around};')
    return "[out:json][timeout:120];\n(\n" + "\n".join(lines) + "\n);\nout center tags;"


WIKIDATA_QUERY = """
SELECT DISTINCT ?item ?itemLabel ?website ?region ?coord ?placeCoord WHERE {
  VALUES ?region { wd:Q752 wd:Q772 wd:Q770 }   # provincies Groningen, Drenthe, Friesland
  ?item wdt:P31/wdt:P279* wd:Q132241 .          # een festival (of een soort festival)
  ?item wdt:P131* ?region .
  ?item wdt:P856 ?website .
  OPTIONAL { ?item wdt:P625 ?coord . }
  OPTIONAL { ?item wdt:P276 ?place . ?place wdt:P625 ?placeCoord . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "nl,en". }
}
LIMIT 2000
"""


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
        place = tags.get("addr:city") or tags.get("addr:place") or ""
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


def distance_km(lat: float, lon: float, center: tuple[float, float] = AREA_CENTER) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat - center[0]), radians(lon - center[1])
    a = sin(dlat / 2) ** 2 + cos(radians(center[0])) * cos(radians(lat)) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def area_of(discovery: dict, radius_km: int = AREA_RADIUS_KM) -> tuple[str, float | None]:
    """'binnen', 'buiten' of 'onbekend', met de afstand tot Groningen als die bekend is."""
    if discovery.get("lat") is not None and discovery.get("lon") is not None:
        km = round(distance_km(float(discovery["lat"]), float(discovery["lon"])), 1)
        return ("binnen" if km <= radius_km else "buiten"), km
    if discovery.get("region") == GRONINGEN_PROVINCE:
        return "binnen", None
    return "onbekend", None


def annotate_area(queue_path: str, discoveries: list[dict], radius_km: int = AREA_RADIUS_KM) -> dict:
    """Schrijf bij elke kandidaat of hij in het werkgebied ligt. Buiten het gebied wordt niet getest."""
    best: dict[str, tuple[str, float | None]] = {}
    rank = {"binnen": 0, "onbekend": 1, "buiten": 2}
    for discovery in discoveries:
        host = host_key(discovery["url"])
        status, km = area_of(discovery, radius_km)
        if host not in best or rank[status] < rank[best[host][0]] or (
                status == best[host][0] and km is not None and (best[host][1] is None or km < best[host][1])):
            best[host] = (status, km)
    path = Path(queue_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
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
            item["policyNote"] = f"buiten het werkgebied ({km} km van Groningen)"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return counts


def _fetch_json(url: str, data: bytes | None = None, timeout: int = 150) -> dict:
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/sparql-results+json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_overpass(radius_km: int) -> dict:
    body = urllib.parse.urlencode({"data": overpass_query(radius_km)}).encode("utf-8")
    return _fetch_json(OVERPASS_URL, data=body)


def fetch_wikidata() -> dict:
    query = urllib.parse.urlencode({"query": WIKIDATA_QUERY, "format": "json"})
    return _fetch_json(f"{WIKIDATA_URL}?{query}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UITNU bronnenmachine")
    parser.add_argument("--queue", default="data/source_candidates.json")
    parser.add_argument("--known", default="collector/web_crawl_sources.json",
                        help="bronnen die al actief zijn en niet opnieuw in de wachtrij hoeven")
    parser.add_argument("--radius-km", type=int, default=AREA_RADIUS_KM)
    parser.add_argument("--osm-json", help="eerder opgeslagen Overpass-antwoord (voor testen)")
    parser.add_argument("--wikidata-json", help="eerder opgeslagen Wikidata-antwoord (voor testen)")
    parser.add_argument("--dry-run", action="store_true", help="alleen tellen, wachtrij niet aanpassen")
    args = parser.parse_args(argv)

    discoveries: list[dict] = []
    problems: list[str] = []
    try:
        osm = json.loads(Path(args.osm_json).read_text(encoding="utf-8")) if args.osm_json else fetch_overpass(args.radius_km)
        discoveries += discoveries_from_overpass(osm)
    except Exception as error:  # een bron die faalt mag de andere niet tegenhouden
        problems.append(f"OpenStreetMap: {error}")
    try:
        wiki = json.loads(Path(args.wikidata_json).read_text(encoding="utf-8")) if args.wikidata_json else fetch_wikidata()
        discoveries += discoveries_from_wikidata(wiki)
    except Exception as error:
        problems.append(f"Wikidata: {error}")

    new = filter_new_hosts(discoveries, load_source_hosts(args.known))
    hosts = {host_key(d["url"]) for d in new}
    print(f"Gevonden: {len(discoveries)} plekken met website, {len(hosts)} nieuwe websites.")
    for problem in problems:
        print(f"Let op, niet gelukt: {problem}")
    if not args.dry_run and new:
        queue = update_queue(args.queue, new)
        print(f"Wachtrij bijgewerkt: {len(queue)} kandidaten in {args.queue}.")
    if not args.dry_run and discoveries and Path(args.queue).exists():
        counts = annotate_area(args.queue, discoveries, args.radius_km)
        print(f"Werkgebied: {counts['binnen']} binnen, {counts['buiten']} buiten (worden niet getest), {counts['onbekend']} onbekend.")
    return 1 if problems and not discoveries else 0


if __name__ == "__main__":
    raise SystemExit(main())
