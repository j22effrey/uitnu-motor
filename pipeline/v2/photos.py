"""Kies bij elk uitje een foto, volgens vaste regel 2.

1. De foto van de organisator, rechtstreeks getoond met naam. Alleen het adres van de foto
   staat in de agenda; de foto zelf wordt niet gekopieerd.
2. Anders een foto van Wikimedia Commons, met maker en licentie: eerst van de plek
   (het gebouw), dan van de plaats (het dorp of de stad).
3. Anders geen foto: de site toont dan een kaart met alleen tekst. Geen illustraties.

Deze module haalt zelf niets op. De zoeker (collector/event_photos.py) vult de cache
data/photos.json; de fabriek leest die hier uit. Zo blijft de fabriek snel en voorspelbaar.
"""
from __future__ import annotations

import re
import unicodedata
import zlib
from urllib.parse import urlparse

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


def page_facts_for(event: dict, cache: dict, lists: set[str]) -> dict:
    """Wat de organisator op de pagina van dit uitje over de soort zegt (uit de cache van de fotozoeker)."""
    pages = cache.get("pages") or {}
    for page in event_pages(event):
        entry = pages.get(page) or {}
        if page not in lists and (entry.get("type") or entry.get("hints")):
            return {k: entry[k] for k in ("type", "hints") if entry.get(k)}
    return {}


def _organizer_photo(event: dict, cache: dict, lists: set[str], names: dict[str, str]) -> dict | None:
    from collector.event_photos import usable_image  # hier pas: de fotozoeker gebruikt zelf de fabriek
    pages = cache.get("pages") or {}
    homepages = cache.get("homepages") or {}
    for page in event_pages(event):
        if page in lists:
            continue
        image = (pages.get(page) or {}).get("image")
        if not image or not usable_image(image, page):
            continue  # ook een eerder bewaard plaatje dat geen foto is (logo, door AI gemaakt)
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


def _pick(record: dict | None, event: dict, slot: int | None = None) -> dict | None:
    """Per gebouw of plaats bewaart de zoeker meerdere foto's; dit uitje krijgt er één van.
    Met 'slot' om de beurt (zie attach_photos), anders vast gekozen op de naam van het uitje."""
    if not record:
        return None
    options = [r for r in record.get("photos") or [] if isinstance(r, dict) and r.get("url")]
    if not options:
        return record if record.get("url") else None
    if slot is None:
        slot = zlib.crc32(str(event.get("slug") or event.get("id") or event.get("title")).encode())
    return options[slot % len(options)]


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


def _commons_source(event: dict, cache: dict) -> tuple[str, dict, str, str] | None:
    """Het gebouw, anders de plaats, waarvan Wikimedia Commons foto's heeft."""
    commons = cache.get("commons") or {}
    city = (event.get("venue") or {}).get("city")
    for key, match, alt in ((venue_key(event), "plek", venue_name(event)), (place_key(event), "plaats", city)):
        record = commons.get(key) if key else None
        if _pick(record, event):
            return key, record, match, alt or ""
    return None


def choose_photo(event: dict, cache: dict, *, lists: set[str], names: dict[str, str],
                 slot: int | None = None) -> dict | None:
    photo = _organizer_photo(event, cache, lists, names)
    if photo:
        return photo
    source = _commons_source(event, cache)
    if not source:
        return None
    _, record, match, alt = source
    return _commons_photo(_pick(record, event, slot), match=match, alt=alt)


def _when(event: dict) -> tuple:
    dates = sorted(o.get("date") or "" for o in event.get("occurrences") or [])
    return (dates[0] if dates else "", norm(event.get("title")), str(event.get("id") or ""))


def attach_photos(events: list[dict], cache: dict, names: dict[str, str] | None = None) -> dict[str, int]:
    """Zet bij elk uitje 'image' (of None) en tel hoe vaak welke soort foto is gekozen.

    Uitjes met foto's van hetzelfde gebouw of dezelfde plaats krijgen op datum om de beurt een
    andere foto, zodat uitjes die in de agenda onder elkaar staan niet dezelfde foto hebben."""
    names = names or {}
    lists = list_pages(events)
    groups: dict[str, list[dict]] = {}
    for event in events:
        source = None if _organizer_photo(event, cache, lists, names) else _commons_source(event, cache)
        if source:
            groups.setdefault(source[0], []).append(event)
    slots = {id(e): i for group in groups.values() for i, e in enumerate(sorted(group, key=_when))}
    counts = {"organisator": 0, "wikimedia": 0, "zonder": 0}
    for event in events:
        photo = choose_photo(event, cache, lists=lists, names=names, slot=slots.get(id(event)))
        event["image"] = photo
        counts[photo["type"] if photo else "zonder"] += 1
    return counts
