"""Kies bij elk uitje een foto, volgens vaste regel 2.

1. De foto van de organisator, rechtstreeks getoond met naam. Alleen het adres van de foto
   staat in de agenda; de foto zelf wordt niet gekopieerd.
2. Anders een foto van Wikimedia Commons, met maker en licentie: eerst van de plek
   (het gebouw), dan van de plaats (het dorp of de stad).
3. Anders geen foto: de site toont dan de eigen illustratie bij de soort uitje.

Deze module haalt zelf niets op. De zoeker (collector/event_photos.py) vult de cache
data/photos.json; de fabriek leest die hier uit. Zo blijft de fabriek snel en voorspelbaar.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from urllib.parse import urlparse

# Een foto van een dorp zegt iets ("dit is in Bourtange"). Bij een plaats met veel uitjes zou
# overal dezelfde foto staan; dan is de illustratie per soort duidelijker en afwisselender.
PLACE_PHOTO_MAX_EVENTS = 4

# Een pagina waar drie of meer verschillende uitjes naar verwijzen is een agendalijst,
# geen pagina van één uitje. De foto daarop hoort niet bij elk uitje afzonderlijk.
LIST_PAGE_MIN_TITLES = 3


def norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def host_of(url: str | None) -> str:
    host = (urlparse(url or "").hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def venue_name(event: dict) -> str | None:
    """De naam van het gebouw, zonder adres erachter ('Forum Groningen, Nieuwe Markt 1')."""
    name = (event.get("venue") or {}).get("name") or ""
    name = name.split(",", 1)[0].strip()
    city = (event.get("venue") or {}).get("city") or ""
    if not name or norm(name) == norm(city) or norm(name).startswith(("diverse", "centrum", "zie ")):
        return None
    return name


def venue_key(event: dict) -> str | None:
    name = venue_name(event)
    city = (event.get("venue") or {}).get("city")
    return f"plek:{norm(name)}|{norm(city)}" if name and city else None


def place_key(event: dict) -> str | None:
    city = (event.get("venue") or {}).get("city")
    return f"plaats:{norm(city)}" if city else None


def event_pages(event: dict) -> list[str]:
    """De pagina's van de organisator over dit uitje, de belangrijkste eerst."""
    pages = [event.get("url")] + [s.get("url") for s in event.get("sources") or []
                                  if s.get("type") == "organisator"]
    return [p for p in dict.fromkeys(pages) if p]


def list_pages(events: list[dict]) -> set[str]:
    titles: dict[str, set[str]] = {}
    for event in events:
        for page in event_pages(event):
            titles.setdefault(page, set()).add(norm(event.get("title")))
    return {page for page, names in titles.items() if len(names) >= LIST_PAGE_MIN_TITLES}


def _organizer_photo(event: dict, cache: dict, lists: set[str], names: dict[str, str]) -> dict | None:
    pages = cache.get("pages") or {}
    homepages = cache.get("homepages") or {}
    for page in event_pages(event):
        if page in lists:
            continue
        image = (pages.get(page) or {}).get("image")
        if not image:
            continue
        host = host_of(page)
        if host not in homepages:
            continue  # voorpagina nog niet bekeken: we weten nog niet of dit de standaardfoto is
        if image == homepages[host].get("image"):
            continue  # de standaardfoto van de hele website, niet van dit uitje
        name = names.get(host) or host
        return {
            "url": image,
            "type": "organisator",
            "match": "uitje",
            "alt": f"Foto bij {event.get('title')}",
            "credit": f"Foto: {name}",
            "sourceUrl": page,
        }
    return None


def _commons_photo(record: dict | None, *, match: str, alt: str) -> dict | None:
    if not record or not record.get("url"):
        return None
    author = record.get("author") or "onbekende maker"
    license_name = record.get("license") or "vrije licentie"
    return {
        "url": record["url"],
        "type": "wikimedia",
        "match": match,
        "alt": alt,
        "credit": f"Foto: {author} · {license_name} · Wikimedia Commons",
        "author": author,
        "license": license_name,
        "licenseUrl": record.get("licenseUrl"),
        "sourceUrl": record.get("pageUrl"),
    }


def choose_photo(event: dict, cache: dict, *, lists: set[str], names: dict[str, str],
                 events_per_place: Counter) -> dict | None:
    photo = _organizer_photo(event, cache, lists, names)
    if photo:
        return photo
    commons = cache.get("commons") or {}
    venue = venue_name(event)
    key = venue_key(event)
    if key:
        photo = _commons_photo(commons.get(key), match="plek", alt=venue or "")
        if photo:
            return photo
    city = (event.get("venue") or {}).get("city")
    key = place_key(event)
    if key and events_per_place[norm(city)] <= PLACE_PHOTO_MAX_EVENTS:
        return _commons_photo(commons.get(key), match="plaats", alt=city or "")
    return None


def attach_photos(events: list[dict], cache: dict, names: dict[str, str] | None = None) -> dict[str, int]:
    """Zet bij elk uitje 'image' (of None) en tel hoe vaak welke soort foto is gekozen."""
    lists = list_pages(events)
    per_place = Counter(norm((e.get("venue") or {}).get("city")) for e in events)
    counts = {"organisator": 0, "wikimedia": 0, "illustratie": 0}
    for event in events:
        photo = choose_photo(event, cache, lists=lists, names=names or {}, events_per_place=per_place)
        event["image"] = photo
        counts[photo["type"] if photo else "illustratie"] += 1
    return counts
