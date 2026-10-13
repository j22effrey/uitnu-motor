"""Een agenda die de website zelf als gegevens (JSON) aanbiedt, zoals het programma van een theater
(Atlas Theater in Emmen: /Umbraco/Api/PerformanceApi/GetPerformances). Per bron ingesteld in
extractorConfig, met de plek van elk gegeven ('Performance.StartTime'):

    endpointUrl  het adres van de gegevens (op de eigen website; robots.txt moet het toestaan)
    items        waar de lijst staat ('' = de gegevens zijn zelf de lijst)
    title        een of meer velden, samen de naam ('Artiest – Voorstelling')
    start, end   begin en eind (ISO 8601)
    url          de pagina van het uitje (mag een pad zijn)
    id           een vaste code van het uitje
    genre        de soort volgens de organisator; genres zet die om naar schema.org ('MusicEvent')
    room         de zaal; rooms zet een zaal om naar een andere plek ({"venue": ..., "city": ...})
    skipTitle    titels die geen uitje zijn (een abonnement of serie)

Alleen feiten: naam, datum en tijd, zaal, soort en link. Geen teksten.
"""
from __future__ import annotations

import json
import re
from typing import Callable
from urllib.parse import urljoin
from urllib.request import Request, build_opener

from collector.site_crawler import USER_AGENT, _SameSiteRedirectHandler, _load_robots, default_fetch
from pipeline.event_model import RawEvent


def value_at(data, path: str | None):
    """Het gegeven op een plek als 'Performance.StartTime' (of '' voor de gegevens zelf)."""
    for part in [p for p in str(path or "").split(".") if p]:
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def _text(value) -> str:
    return " ".join(str(value or "").split())


def parse_items(payload, config: dict, *, source_name: str, root_url: str) -> list[RawEvent]:
    items = value_at(payload, config.get("items") or "")
    if not isinstance(items, list):
        return []
    skip = re.compile(config["skipTitle"], re.I) if config.get("skipTitle") else None
    genres = config.get("genres") if isinstance(config.get("genres"), dict) else {}
    rooms = config.get("rooms") if isinstance(config.get("rooms"), dict) else {}
    paths = config.get("title") if isinstance(config.get("title"), list) else [config.get("title")]
    out: list[RawEvent] = []
    for item in items:
        parts: list[str] = []
        for path in paths:
            text = _text(value_at(item, path))
            if text and text.casefold() not in {p.casefold() for p in parts}:
                parts.append(text)
        title = " – ".join(parts)
        start = _text(value_at(item, config.get("start")))
        if not title or not start or (skip and skip.search(title)):
            continue
        link = _text(value_at(item, config.get("url"))) if config.get("url") else ""
        genre = _text(value_at(item, config.get("genre"))) if config.get("genre") else ""
        room = _text(value_at(item, config.get("room"))) if config.get("room") else ""
        place = rooms.get(room)
        place = {"venue": place} if isinstance(place, str) else (place if isinstance(place, dict) else {})
        out.append(RawEvent(
            source_name=source_name,
            source_type="structured_web",
            source_url=urljoin(root_url, link) if link else root_url,
            source_id=_text(value_at(item, config.get("id"))) or None,
            title=title,
            start_at=start,
            end_at=_text(value_at(item, config.get("end"))) or None,
            venue=place.get("venue"),
            city=place.get("city"),
            category=genres.get(genre) or genre or None,
            verification_status="organizer_confirmed",
            raw={"source_feed": config.get("endpointUrl"), "genre": genre or None, "room": room or None},
        ))
    return out


def _fetch_json_text(url: str, *, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with build_opener(_SameSiteRedirectHandler()).open(request, timeout=timeout) as response:
        return response.read(8_000_000).decode(response.headers.get_content_charset() or "utf-8", "replace")


def fetch(config: dict, *, source_name: str, root_url: str, timeout: float = 15,
          robots_fetch: Callable = default_fetch, json_fetch: Callable[..., str] = _fetch_json_text) -> list[RawEvent]:
    endpoint = str(config.get("endpointUrl") or "")
    if not endpoint:
        raise ValueError("json_api zonder extractorConfig.endpointUrl")
    robots, _ = _load_robots(root_url, robots_fetch, timeout=timeout)
    if not robots.can_fetch(USER_AGENT, endpoint):
        raise PermissionError(f"robots.txt staat {endpoint} niet toe")
    return parse_items(json.loads(json_fetch(endpoint, timeout=timeout)), config,
                       source_name=source_name, root_url=root_url)
