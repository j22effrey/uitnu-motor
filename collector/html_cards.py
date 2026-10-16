"""Een agenda van kaartjes op de eigen website, met een vaste opbouw per kaartje (SPOT, Vera, Simplon, Forum).

Per bron ingesteld in extractorConfig, zonder nieuwe code per website:

    endpointUrl  de pagina (of het stukje HTML dat de pagina zelf ophaalt) met de kaartjes
    pageParam, maxPages, firstPage  bladeren: ?p=1, ?p=2, ... tot een pagina zonder kaartjes
    card         waar een kaartje begint (een reguliere expressie, bijv. '<article class="program__item"')
    fields       per gegeven een reguliere expressie met één groep, binnen het kaartje:
                 title, extra (wordt achter de titel gezet), start (ISO), date (tekst), time, end,
                 url, id, genre, room, tags
    dropFromTitle  wat uit de titel weg moet (bijv. '<sup.*?</sup>' voor het land van een band)
    genres       de soort volgens de organisator -> schema.org ('muziek' -> 'MusicEvent'); bij een lijst
                 van kenmerken telt het eerste kenmerk dat in de lijst staat
    rooms        een zaal -> een andere plek ({"venue": ..., "city": ...}) of alleen een zaalnaam
    skipTitle    titels die geen uitje zijn; skipUrl: links die geen uitje zijn ('/abonnement-')
    skipExtra    een toevoeging achter de titel die niets zegt ('support')
    roomFallback de plek als de zaal niet in rooms staat ('elders': alleen de stad, geen zaal)
    skipTags     kenmerken die geen uitje zijn ('Spreekuur', 'Basisvaardigheden')

Datums in de vormen van collector/when.py ('do 15.10', 'Thursday 15 October', '16-10-2026 / 10:00').
Alleen feiten: naam, datum en tijd, zaal, soort en link. Geen teksten. robots.txt geldt voor elke pagina.
"""
from __future__ import annotations

import re
from datetime import date
from html import unescape
from typing import Callable
from urllib.parse import urljoin

from collector.json_api_events import with_param
from collector.site_crawler import USER_AGENT, _load_robots, default_fetch
from collector.when import parse_when
from pipeline.event_model import RawEvent


def _clean(value) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", unescape(str(value or ""))).split())


def _field(card: str, pattern: str | None) -> str:
    if not pattern:
        return ""
    m = re.search(pattern, card, re.I | re.S)
    return m.group(1) if m else ""


def _map(mapping: dict, value: str):
    """De vertaling van een waarde: precies, of het eerste kenmerk uit de lijst dat in de waarde staat."""
    if not mapping or not value:
        return None
    if value in mapping:
        return mapping[value]
    low = value.casefold()
    for key, target in mapping.items():
        if re.search(rf"(?<![\w-]){re.escape(key.casefold())}(?![\w-])", low):
            return target
    return None


def split_cards(html: str, start: str) -> list[str]:
    marks = [m.start() for m in re.finditer(start, html, re.I)]
    return [html[a:b] for a, b in zip(marks, marks[1:] + [len(html)])]


def parse_cards(html: str, config: dict, *, source_name: str, page_url: str, today: date | None = None) -> list[RawEvent]:
    fields = config.get("fields") if isinstance(config.get("fields"), dict) else {}
    skip = re.compile(config["skipTitle"], re.I) if config.get("skipTitle") else None
    skip_tags = re.compile(config["skipTags"], re.I) if config.get("skipTags") else None
    drop = re.compile(config["dropFromTitle"], re.I | re.S) if config.get("dropFromTitle") else None
    skip_url = re.compile(config["skipUrl"], re.I) if config.get("skipUrl") else None
    skip_extra = re.compile(config["skipExtra"], re.I) if config.get("skipExtra") else None
    fallback = config.get("roomFallback") if isinstance(config.get("roomFallback"), dict) else None
    genres = config.get("genres") if isinstance(config.get("genres"), dict) else {}
    rooms = config.get("rooms") if isinstance(config.get("rooms"), dict) else {}
    out: list[RawEvent] = []
    seen: set[tuple] = set()
    for card in split_cards(html, config.get("card") or r"<article\b"):
        raw_title = _field(card, fields.get("title"))
        title = _clean(drop.sub(" ", raw_title) if drop else raw_title)
        raw_extra = _field(card, fields.get("extra"))
        extra = _clean(drop.sub(" ", raw_extra) if drop else raw_extra)
        if skip_extra and skip_extra.search(extra):
            extra = ""
        if extra and extra.casefold() not in title.casefold():
            title = f"{title} – {extra}" if title else extra
        if not title or (skip and skip.search(title)):
            continue
        tags = _clean(_field(card, fields.get("tags")))
        if skip_tags and tags and skip_tags.search(tags):
            continue
        start = _clean(_field(card, fields.get("start")))
        if start and not re.match(r"20\d{2}-\d{2}-\d{2}", start):
            start = parse_when(start, today=today) or ""
        if not start:
            start = parse_when(_clean(_field(card, fields.get("date"))), _clean(_field(card, fields.get("time"))),
                               today=today) or ""
        if not start:
            continue
        end = _clean(_field(card, fields.get("end")))
        if end and not re.match(r"20\d{2}-\d{2}-\d{2}", end):
            end_time = parse_when(start[:10], end, today=today)
            end = end_time if end_time and "T" in end_time else ""
        link = _clean(_field(card, fields.get("url")))
        if skip_url and link and skip_url.search(link):
            continue
        genre = _clean(_field(card, fields.get("genre"))) or tags
        room = _clean(_field(card, fields.get("room")))
        place = _map(rooms, room)
        if place is None and fields.get("room") and fallback:
            place = fallback  # een zaal die we niet kennen ('elders'): niet de vaste zaal invullen
        place = {"venue": place} if isinstance(place, str) else (place if isinstance(place, dict) else {})
        key = (title, start, link)
        if key in seen:
            continue  # hetzelfde kaartje staat vaker op de pagina (uitgelicht en in de lijst)
        seen.add(key)
        out.append(RawEvent(
            source_name=source_name,
            source_type="structured_web",
            source_url=urljoin(page_url, link) if link else page_url,
            source_id=_clean(_field(card, fields.get("id"))) or None,
            title=title,
            start_at=start,
            end_at=end or None,
            venue=place.get("venue"),
            city=place.get("city"),
            lat=place.get("lat"),
            lon=place.get("lon"),
            category=_map(genres, genre) or genre or None,
            verification_status="organizer_confirmed",
            raw={"source_feed": page_url, "genre": genre or None, "room": room or None},
        ))
    return out


def fetch(config: dict, *, source_name: str, root_url: str, timeout: float = 15,
          page_fetch: Callable = default_fetch, today: date | None = None) -> list[RawEvent]:
    endpoint = str(config.get("endpointUrl") or "")
    if not endpoint:
        raise ValueError("html_cards zonder extractorConfig.endpointUrl")
    robots, _ = _load_robots(root_url, page_fetch, timeout=timeout)
    param = config.get("pageParam")
    first = int(config.get("firstPage") or 1)
    urls = [endpoint] if not param else [with_param(endpoint, param, n)
                                          for n in range(first, first + int(config.get("maxPages") or 10))]
    out: list[RawEvent] = []
    seen_pages: set[str] = set()
    for url in urls:
        if not robots.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt staat {url} niet toe")
        page = page_fetch(url, timeout=timeout)
        events = parse_cards(page.text, config, source_name=source_name, page_url=page.url or url, today=today)
        # Een pagina zonder kaartjes, of dezelfde als de vorige (de site negeert het paginanummer): klaar.
        # (Een pagina waarvan alle kaartjes wegvallen, zoals alleen spreekuren, telt niet als einde.)
        cards = split_cards(page.text, config.get("card") or r"<article\b")
        key = "|".join(cards)
        if not cards or key in seen_pages:
            break
        seen_pages.add(key)
        out.extend(events)
    return out
