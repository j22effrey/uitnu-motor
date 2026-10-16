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
    startDate    in plaats van 'start': de dag in een eigen veld, ook als getal (seconden sinds 1970) of
                 als Nederlandse tekst ('za 17 okt 2026'); startTime: de tijd in een eigen veld ('20:30')
    skipField, skipValue  een uitje overslaan als dat veld bij deze tekst past (bijv. de categorie 'Archief')
    pageParam, maxPages   bladeren: ?page=1, ?page=2, ... tot een lege lijst (hooguit maxPages)

Alleen feiten: naam, datum en tijd, zaal, soort en link. Geen teksten.
"""
from __future__ import annotations

import json
import re
from datetime import date
from html import unescape
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from collector.site_crawler import USER_AGENT, _SameSiteRedirectHandler, _load_robots, default_fetch
from collector.when import parse_when
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


def _clean(value) -> str:
    """Tekst zonder HTML-tekens en -codes ('Rock &#8211; Live' -> 'Rock – Live')."""
    return _text(re.sub(r"<[^>]+>", " ", unescape(str(value or ""))))


ISO_START = re.compile(r"^20\d{2}-\d{2}-\d{2}")


def _moment(item, config: dict, key: str, today: date | None) -> str:
    """Begin of eind: een ISO-veld, of dag en tijd apart (in allerlei vormen, zie collector/when.py)."""
    if config.get(key):
        value = _text(value_at(item, config.get(key)))
        return value if not value or ISO_START.match(value) else (parse_when(value, today=today) or "")
    if config.get(f"{key}Date"):
        day = value_at(item, config.get(f"{key}Date"))
        clock = value_at(item, config.get(f"{key}Time")) if config.get(f"{key}Time") else None
        return parse_when(day, clock, today=today) or ""
    return ""


def parse_items(payload, config: dict, *, source_name: str, root_url: str, today: date | None = None) -> list[RawEvent]:
    items = value_at(payload, config.get("items") or "")
    if not isinstance(items, list):
        return []
    skip = re.compile(config["skipTitle"], re.I) if config.get("skipTitle") else None
    skip_value = re.compile(config["skipValue"], re.I) if config.get("skipField") and config.get("skipValue") else None
    genres = config.get("genres") if isinstance(config.get("genres"), dict) else {}
    rooms = config.get("rooms") if isinstance(config.get("rooms"), dict) else {}
    paths = config.get("title") if isinstance(config.get("title"), list) else [config.get("title")]
    out: list[RawEvent] = []
    for item in items:
        parts: list[str] = []
        for path in paths:
            text = _clean(value_at(item, path))
            if text and text.casefold() not in {p.casefold() for p in parts}:
                parts.append(text)
        title = " – ".join(parts)
        start = _moment(item, config, "start", today)
        if not title or not start or (skip and skip.search(title)):
            continue
        if skip_value and skip_value.search(json.dumps(value_at(item, config["skipField"]), ensure_ascii=False)):
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
            end_at=_moment(item, config, "end", today) or None,
            venue=place.get("venue"),
            city=place.get("city"),
            lat=place.get("lat"),
            lon=place.get("lon"),
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
    param = config.get("pageParam")
    if not param:
        return parse_items(json.loads(json_fetch(endpoint, timeout=timeout)), config,
                           source_name=source_name, root_url=root_url)
    # Bladeren tot een lege lijst.
    out: list[RawEvent] = []
    previous = None
    for page in range(1, int(config.get("maxPages") or 10) + 1):
        try:
            payload = json.loads(json_fetch(with_param(endpoint, param, page), timeout=timeout))
        except HTTPError as exc:
            # WordPress geeft na de laatste pagina een foutcode (400): dan zijn we klaar.
            if page > 1 and exc.code in (400, 404):
                break
            raise
        items = value_at(payload, config.get("items") or "")
        # Klaar bij een lege lijst, of als de site na de laatste pagina die nog een keer geeft.
        if not isinstance(items, list) or not items or items == previous:
            break
        previous = items
        out.extend(parse_items(payload, config, source_name=source_name, root_url=root_url))
    return out


def with_param(url: str, name: str, value) -> str:
    """Het adres met ?name=value (een bestaande waarde wordt vervangen)."""
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != name] + [(name, str(value))]
    return urlunparse(parts._replace(query=urlencode(query)))
