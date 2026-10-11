"""Execute active UITNU sources with the extractor proven during probing.

This is the bridge between source activation and ingestion. It keeps one active
source registry while dispatching to JSON-LD/site crawl, WordPress/The Events
Calendar, ICS, or the strict Dutch HTML agenda extractor.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
import argparse
import json
from pathlib import Path
from typing import Callable, Iterable

from collector import ics_events, wordpress_events
from collector.site_crawler import CrawlResult, CrawlSource, crawl_source
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
    return [x for x in values if isinstance(x, dict) and x.get("enabled", True)]


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


def run_source(
    source: dict,
    *,
    site_runner: Callable[..., CrawlResult] = crawl_source,
    wordpress_fetch: Callable[..., tuple[list[RawEvent], dict]] = wordpress_events.fetch,
    ics_fetch: Callable[..., list[RawEvent]] = ics_events.fetch,
    timeout: float = 15,
) -> SourceRunResult:
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
        crawl = site_runner(CrawlSource.from_dict(crawl_config), timeout=timeout)
        return SourceRunResult(
            source_id=source_id,
            extractor=extractor,
            events=crawl.events,
            diagnostics={
                "pages_visited": len(crawl.pages_visited),
                "blocked_by_robots": len(crawl.blocked_by_robots),
                "external_candidates": len(crawl.external_candidates),
                "errors": crawl.errors[:10],
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
) -> dict[str, SourceRunResult]:
    values = [x for x in sources if isinstance(x, dict) and x.get("enabled", True)]
    if not values:
        return {}
    out: dict[str, SourceRunResult] = {}
    max_workers = max(1, min(int(workers or 1), 8, len(values)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                run_source,
                source,
                site_runner=site_runner,
                wordpress_fetch=wordpress_fetch,
                ics_fetch=ics_fetch,
                timeout=timeout,
            ): source
            for source in values
        }
        for future in as_completed(futures):
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
