"""Generic WordPress/The Events Calendar REST adapter.

The Events Calendar exposes factual event fields through a public REST endpoint on
many organizer websites. UITNU uses this only when a source explicitly exposes the
endpoint; it does not crawl arbitrary WordPress content or copy editorial text/images.
"""
from __future__ import annotations

from dataclasses import replace
from html import unescape
from html.parser import HTMLParser
import json
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from pipeline.event_model import RawEvent

USER_AGENT = "UITNU/0.13 (+public-event-feed)"
TRIBE_PATH = "/wp-json/tribe/events/v1/events"


def build_url(base_url: str, *, start_date: str | None = None,
              end_date: str | None = None, page: int = 1,
              per_page: int = 100) -> str:
    parsed = urlparse(base_url)
    if not (parsed.scheme in {"http", "https"} and parsed.netloc):
        raise ValueError("base_url must be an absolute http(s) URL")
    root = f"{parsed.scheme}://{parsed.netloc}"
    params = {"page": max(1, int(page)), "per_page": min(max(int(per_page), 1), 100)}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return root + TRIBE_PATH + "?" + urlencode(params)


def _float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _text(value):
    if isinstance(value, str):
        value = unescape(value).strip()
        return value or None
    if isinstance(value, dict):
        rendered = value.get("rendered")
        if isinstance(rendered, str):
            rendered = unescape(rendered).strip()
            return rendered or None
    return None


def parse_payload(payload: dict, *, source_name: str, source_base_url: str) -> list[RawEvent]:
    items = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    out: list[RawEvent] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title")) or _text(item.get("name"))
        start = item.get("start_date") or item.get("start_date_details") or item.get("start")
        if isinstance(start, dict):
            start = start.get("datetime") or start.get("date")
        if not (title and isinstance(start, str) and start.strip()):
            continue
        venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}
        organizer = item.get("organizer") if isinstance(item.get("organizer"), list) else []
        categories = item.get("categories") if isinstance(item.get("categories"), list) else []
        source_url = item.get("url") or item.get("website") or source_base_url
        if isinstance(source_url, str):
            source_url = urljoin(source_base_url, source_url)
        else:
            source_url = source_base_url
        address_parts = [venue.get("address"), venue.get("address_2")]
        address = " ".join(str(x).strip() for x in address_parts if x)
        category = None
        if categories:
            first = categories[0]
            if isinstance(first, dict):
                category = _text(first.get("name"))
            elif isinstance(first, str):
                category = _text(first)
        lat = _float(venue.get("geo_lat") or venue.get("lat") or item.get("geo_lat") or item.get("latitude"))
        lon = _float(venue.get("geo_lng") or venue.get("lng") or item.get("geo_lng") or item.get("longitude"))
        end = item.get("end_date") or item.get("end")
        out.append(RawEvent(
            source_name=source_name,
            source_type="structured_web",
            source_url=source_url,
            source_id=str(item.get("id") or "") or None,
            title=title,
            start_at=start.strip(),
            end_at=end.strip() if isinstance(end, str) and end.strip() else None,
            venue=_text(venue.get("venue")) or _text(venue.get("name")),
            address=address or None,
            city=_text(venue.get("city")),
            lat=lat,
            lon=lon,
            category=category,
            price_text=_text(item.get("cost")),
            verification_status="organizer_confirmed",
            raw={
                "source": "wordpress_the_events_calendar",
                "all_day": bool(item.get("all_day")),
                "organizer_count": len(organizer),
            },
        ))
    return out


_DETAIL_CLASS_FIELDS = {
    "tribe-venue": "venue",
    "tribe-street-address": "street",
    "tribe-locality": "city",
    "tribe-postal-code": "postal_code",
}


class _DetailLocationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.active: list[dict] = []
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag.lower())
        classes = set()
        for key, value in attrs:
            if key.lower() == "class" and value:
                classes.update(str(value).split())
        for css_class, field in _DETAIL_CLASS_FIELDS.items():
            if css_class in classes and field not in self.values:
                self.active.append({"field": field, "depth": len(self.stack), "parts": []})

    def handle_data(self, data):
        if not data.strip():
            return
        for capture in self.active:
            capture["parts"].append(data)

    def handle_endtag(self, tag):
        depth = len(self.stack)
        finished = [x for x in self.active if x["depth"] == depth]
        for capture in finished:
            value = unescape(" ".join(capture["parts"]))
            value = " ".join(value.split()).strip(" ,")
            if value and capture["field"] not in self.values:
                self.values[capture["field"]] = value
            self.active.remove(capture)
        if self.stack:
            self.stack.pop()


def parse_detail_location(html: str) -> dict[str, str | None]:
    parser = _DetailLocationParser()
    parser.feed(html)
    return {
        "venue": parser.values.get("venue"),
        "street": parser.values.get("street"),
        "city": parser.values.get("city"),
        "postal_code": parser.values.get("postal_code"),
    }


def fetch_detail_location(url: str, timeout: float = 15) -> dict[str, str | None]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(req, timeout=timeout) as response:
        html = response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")
    return parse_detail_location(html)


def _choose_pdok_result(results, city: str | None):
    if not results:
        return None
    city_low = (city or "").casefold().strip()
    if not city_low:
        return results[0]
    matching = [
        r for r in results
        if city_low in (r.label or "").casefold()
        or city_low == (r.municipality or "").casefold()
    ]
    return matching[0] if matching else None


def enrich_location(event: RawEvent, *, timeout: float = 15, geocode_missing: bool = True) -> RawEvent:
    """Fill missing location facts from the public event page and PDOK.

    Existing feed values always win. If a city is known, PDOK coordinates are only
    accepted when the result label or municipality agrees with that city.
    """
    if event.city and (event.lat is not None and event.lon is not None):
        return event
    detail: dict[str, str | None] = {}
    try:
        detail = fetch_detail_location(event.source_url, timeout=timeout)
    except Exception:
        detail = {}
    venue = event.venue or detail.get("venue")
    address = event.address or detail.get("street")
    city = event.city or detail.get("city")
    lat, lon = event.lat, event.lon
    geocode_label = None
    if geocode_missing and (lat is None or lon is None) and (address or city or venue):
        from collector.pdok_geocode import geocode
        query = " ".join(x for x in [address, city] if x) or " ".join(x for x in [venue, city] if x)
        try:
            results = geocode(query, rows=8, timeout=min(timeout, 10))
        except Exception:
            results = []
        chosen = _choose_pdok_result(results, city)
        if chosen:
            lat, lon, geocode_label = chosen.lat, chosen.lon, chosen.label
    raw = dict(event.raw or {})
    raw["detail_location"] = {k: v for k, v in detail.items() if v}
    if geocode_label:
        raw["pdok_label"] = geocode_label
    return replace(event, venue=venue, address=address, city=city, lat=lat, lon=lon, raw=raw)


def fetch(base_url: str, *, source_name: str | None = None,
          start_date: str | None = None, end_date: str | None = None,
          page: int = 1, per_page: int = 100, timeout: float = 15) -> tuple[list[RawEvent], dict]:
    url = build_url(base_url, start_date=start_date, end_date=end_date, page=page, per_page=per_page)
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        payload = json.load(response)
    name = source_name or urlparse(base_url).netloc
    return parse_payload(payload, source_name=name, source_base_url=base_url), payload
