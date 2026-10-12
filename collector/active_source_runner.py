"""Execute active UITNU sources with the extractor proven during probing.

This is the bridge between source activation and ingestion. It keeps one active
source registry while dispatching to JSON-LD/site crawl, WordPress/The Events
Calendar, ICS, or the strict Dutch HTML agenda extractor.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from dataclasses import asdict, dataclass, replace
import argparse
import json
from pathlib import Path
import time
from typing import Callable, Iterable

from collector import ics_events, wordpress_events
from collector.discover_venues import is_excluded
from collector.site_crawler import TIME_UP, CrawlResult, CrawlSource, crawl_source
from pipeline.event_model import RawEvent

SUPPORTED = {"jsonld_event", "wordpress_tribe", "ics", "html_agenda_dutch"}


@dataclass
class SourceRunResult:
    source_id: str
    extractor: str
    events: list[RawEvent]
    diagnostics: dict
    error: str | None = None

    def asdict(self) -> dict:
        return {
            "source_id": self.source_id,
            "extractor": self.extractor,
            "events": [asdict(x) for x in self.events],
            "diagnostics": self.diagnostics,
            "error": self.error,
        }


def load_active_sources(path: str | Path) -> list[dict]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    values = payload.get("sources", []) if isinstance(payload, dict) else []
    if not isinstance(values, list):
        raise ValueError("active source registry must contain a sources list")
    # Vaste regel 1: een website op de uitsluitlijst nooit ophalen, ook niet als hij ooit is aangezet.
    return [x for x in values if isinstance(x, dict) and x.get("enabled", True)
            and not is_excluded(str(x.get("rootUrl") or ""))]


def _apply_trust(event: RawEvent, role: str) -> RawEvent:
    """Normalize adapter output to the same trust semantics as the site crawler."""
    raw = dict(event.raw or {})
    raw["activated_role"] = role
    raw["description_removed_by_runner"] = bool(event.description)
    trusted = role in {"organizer", "venue"}
    return replace(
        event,
        source_type="structured_web" if trusted else "discovery_web",
        verification_status="organizer_confirmed" if trusted else "unknown",
        description=None,
        raw=raw,
    )


def default_place(source: dict) -> dict | None:
    """De vaste plek van een podium, voor uitjes waarvan de agenda geen plaats noemt."""
    place = source.get("defaultPlace")
    if not isinstance(place, dict) or not str(place.get("city") or "").strip():
        return None
    return place


def apply_default_place(event: RawEvent, place: dict | None) -> RawEvent:
    """Vul alleen een plek in als het uitje zelf helemaal geen plaats heeft."""
    if not place:
        return event
    if event.city or event.address or (event.lat is not None and event.lon is not None):
        return event
    venue = str(place.get("venue") or "").strip() or None
    if event.venue and venue and event.venue.casefold() != venue.casefold():
        return event  # de agenda noemt een andere zaal: niet gokken
    # Zonder vaste zaal (een dorpswebsite) is alleen de plaats bekend: die klopt ook als de agenda
    # een zaal in het dorp noemt.
    raw = dict(event.raw or {})
    raw["place_from_source"] = True
    return replace(
        event,
        venue=event.venue or venue,
        city=str(place["city"]).strip(),
        lat=place.get("lat"),
        lon=place.get("lon"),
        raw=raw,
    )


def run_source(source: dict, **kwargs) -> SourceRunResult:
    result = _run_source(source, **kwargs)
    place = default_place(source)
    if place:
        result.events = [apply_default_place(x, place) for x in result.events]
    return result


def _run_source(
    source: dict,
    *,
    site_runner: Callable[..., CrawlResult] = crawl_source,
    wordpress_fetch: Callable[..., tuple[list[RawEvent], dict]] = wordpress_events.fetch,
    ics_fetch: Callable[..., list[RawEvent]] = ics_events.fetch,
    timeout: float = 15,
    deadline: float | None = None,
    source_seconds: float | None = None,
) -> SourceRunResult:
    if source_seconds:
        # Elke bron krijgt hoogstens zoveel tijd: één trage website mag de rest niet ophouden.
        own = time.monotonic() + source_seconds
        deadline = own if deadline is None else min(deadline, own)
    source_id = str(source.get("id") or "")
    if not source_id:
        raise ValueError("source id is required")
    extractor = str(source.get("extractorHint") or "jsonld_event")
    if extractor not in SUPPORTED:
        raise ValueError(f"unsupported active extractor: {extractor}")
    name = str(source.get("name") or source_id)
    root = str(source.get("rootUrl") or "")
    role = str(source.get("role") or "discovery")
    config = source.get("extractorConfig") if isinstance(source.get("extractorConfig"), dict) else {}

    if extractor in {"jsonld_event", "html_agenda_dutch"}:
        crawl_config = dict(source)
        crawl_config["extractorHint"] = extractor
        extra = {"deadline": deadline} if deadline is not None else {}
        crawl = site_runner(CrawlSource.from_dict(crawl_config), timeout=timeout, **extra)
        return SourceRunResult(
            source_id=source_id,
            extractor=extractor,
            events=crawl.events,
            diagnostics={
                "pages_visited": len(crawl.pages_visited),
                "blocked_by_robots": len(crawl.blocked_by_robots),
                "external_candidates": len(crawl.external_candidates),
                "errors": crawl.errors[:10],
                **({"tijdOp": True} if TIME_UP in crawl.errors else {}),
            },
        )

    if extractor == "wordpress_tribe":
        # The previous runner only collected page 1 (maximum 100 events).
        # Follow only a bounded number of pages on an explicitly active feed.
        max_pages = max(1, min(int(config.get("maxFeedPages", 8)), 12))
        normalized: list[RawEvent] = []
        seen: set[tuple] = set()
        pages_fetched = 0
        last_payload: dict = {}
        partial_error = None
        for page in range(1, max_pages + 1):
            if page > 1 and deadline is not None and time.monotonic() >= deadline:
                partial_error = TIME_UP
                break
            kwargs = {"source_name": name, "per_page": 100, "timeout": timeout}
            if page > 1:
                kwargs["page"] = page
            try:
                page_events, payload = wordpress_fetch(root, **kwargs)
            except Exception as exc:
                if not pages_fetched:
                    raise
                partial_error = f"{type(exc).__name__}: {exc}"
                break
            pages_fetched += 1
            last_payload = payload if isinstance(payload, dict) else {}
            new_count = 0
            for event in page_events:
                key = (
                    event.source_id or event.source_url,
                    event.start_at,
                    event.title.casefold(),
                )
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(_apply_trust(event, role))
                new_count += 1
            if not page_events or not new_count:
                break
            total_pages = last_payload.get("total_pages")
            try:
                known_pages = int(total_pages) if total_pages is not None else None
            except (TypeError, ValueError):
                known_pages = None
            if known_pages is not None and page >= known_pages:
                break
            if known_pages is None and not last_payload.get("next_rest_url") and len(page_events) < 100:
                break
        return SourceRunResult(
            source_id=source_id,
            extractor=extractor,
            events=normalized,
            error=partial_error,
            diagnostics={
                "feed_event_count": len(normalized),
                "pages_fetched": pages_fetched,
                "max_feed_pages": max_pages,
                "partial_error": partial_error,
                "next_rest_url": last_payload.get("next_rest_url"),
                **({"tijdOp": True} if partial_error == TIME_UP else {}),
            },
        )

    feed_url = str(config.get("feedUrl") or "")
    if not feed_url:
        raise ValueError(f"ICS source {source_id} has no extractorConfig.feedUrl")
    events = ics_fetch(feed_url, source_name=name, timeout=timeout)
    normalized = [_apply_trust(x, role) for x in events]
    return SourceRunResult(
        source_id=source_id,
        extractor=extractor,
        events=normalized,
        diagnostics={"feed_url": feed_url, "feed_event_count": len(events)},
    )


def run_all(
    sources: Iterable[dict],
    *,
    workers: int = 4,
    timeout: float = 15,
    site_runner: Callable[..., CrawlResult] = crawl_source,
    wordpress_fetch: Callable[..., tuple[list[RawEvent], dict]] = wordpress_events.fetch,
    ics_fetch: Callable[..., list[RawEvent]] = ics_events.fetch,
    budget_seconds: float | None = None,
    source_seconds: float | None = None,
) -> dict[str, SourceRunResult]:
    """Alle actieve bronnen ophalen, een paar tegelijk.

    Met een tijdsbudget halen de bronnen na die tijd geen nieuwe pagina's meer op; wat ze al
    gevonden hebben telt mee. Een bron die dan nog niet klaar is, staat erin met 'tijd op'.
    source_seconds: hoogstens zoveel tijd per bron (een trage website houdt de rest niet op)."""
    values = [x for x in sources if isinstance(x, dict) and x.get("enabled", True)]
    if not values:
        return {}
    deadline = time.monotonic() + budget_seconds if budget_seconds else None
    extra = {"deadline": deadline} if deadline is not None else {}
    if source_seconds:
        extra["source_seconds"] = source_seconds
    out: dict[str, SourceRunResult] = {}
    # Elke bron is een andere website: meer tegelijk is geen extra belasting voor één site.
    max_workers = max(1, min(int(workers or 1), 16, len(values)))
    pool = ThreadPoolExecutor(max_workers=max_workers)
    futures = {
        pool.submit(
            run_source,
            source,
            site_runner=site_runner,
            wordpress_fetch=wordpress_fetch,
            ics_fetch=ics_fetch,
            timeout=timeout,
            **extra,
        ): source
        for source in values
    }
    # Na het budget nog even wachten op pagina's die al onderweg waren, dan niet langer.
    wait = budget_seconds + 3 * timeout + 30 if budget_seconds else None
    try:
        for future in as_completed(futures, timeout=wait):
            source = futures[future]
            sid = str(source.get("id") or "unknown")
            try:
                out[sid] = future.result()
            except Exception as exc:
                out[sid] = SourceRunResult(
                    source_id=sid,
                    extractor=str(source.get("extractorHint") or "jsonld_event"),
                    events=[],
                    diagnostics={},
                    error=f"{type(exc).__name__}: {exc}",
                )
    except FuturesTimeout:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    for source in values:
        sid = str(source.get("id") or "unknown")
        if sid not in out:
            out[sid] = SourceRunResult(source_id=sid, extractor=str(source.get("extractorHint") or "jsonld_event"),
                                       events=[], diagnostics={"tijdOp": True}, error=TIME_UP)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run UITNU active sources using their proven extractor")
    parser.add_argument("--sources", default="collector/web_crawl_sources.json")
    parser.add_argument("--source-id")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    sources = load_active_sources(args.sources)
    if args.source_id:
        sources = [x for x in sources if x.get("id") == args.source_id]
        if not sources:
            raise SystemExit(f"unknown or disabled source id: {args.source_id}")
    results = run_all(sources, workers=args.workers, timeout=args.timeout)
    print(json.dumps(
        {key: value.asdict() for key, value in results.items()},
        ensure_ascii=False,
        indent=2 if args.pretty else None,
    ))
