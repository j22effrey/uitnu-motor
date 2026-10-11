"""Safely probe source candidates for extraction methods UITNU already supports.

Probing does not activate a source. It records technical capability only:
WordPress/The Events Calendar, Schema.org Event JSON-LD, ICS, or UITNU's strict
Dutch HTML agenda fallback.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import os
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from collector.dutch_agenda_html import parse_agenda
from collector.jsonld_events import parse_html
from collector.site_crawler import CrawlSource, Fetched, USER_AGENT, crawl_source, default_fetch
from collector.source_candidates import candidate_priority, canonical_url
from collector.wordpress_events import build_url as wordpress_events_url


@dataclass(frozen=True)
class ProbeResult:
    url: str
    host: str
    robots_status: str
    probe_status: str
    extractors: list[str]
    suggested_extractor: str | None
    details: dict
    error: str | None = None


class _CalendarLinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.ics_urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() not in {"a", "link"}:
            return
        values = {str(k).lower(): str(v) for k, v in attrs if v is not None}
        href = values.get("href", "").strip()
        type_value = values.get("type", "").casefold()
        if not href:
            return
        if href.casefold().split("?", 1)[0].endswith(".ics") or "text/calendar" in type_value:
            url = canonical_url(urljoin(self.base_url, href))
            if url and url not in self.ics_urls:
                self.ics_urls.append(url)


def _robots_for(url: str, fetcher: Callable[..., Fetched], timeout: float) -> tuple[RobotFileParser, str]:
    p = urlparse(url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        fetched = fetcher(robots_url, timeout=timeout)
        if 200 <= fetched.status < 300:
            rp.parse(fetched.text.splitlines())
            return rp, "loaded"
    except Exception:
        pass
    # Safety invariant: an unavailable robots policy is not permission to crawl.
    # Keep the candidate for a later retry, but perform no site requests now.
    rp.parse(["User-agent: *", "Disallow: /"])
    return rp, "unavailable"


def _shallow_structured_probe(
    origin: str,
    *,
    fetcher: Callable[..., Fetched],
    timeout: float,
    max_pages: int,
) -> dict:
    """Sample a few event-prioritized pages for JSON-LD hidden beyond the lead URL."""
    if max_pages <= 0:
        return {"events": 0, "pages": []}
    source = CrawlSource(
        id="probe",
        name="Probe",
        root_url=origin,
        role="discovery",
        enabled=True,
        max_pages=max(1, min(int(max_pages), 8)),
        max_depth=1,
        min_delay_seconds=0,
    )
    result = crawl_source(
        source,
        fetcher=fetcher,
        timeout=timeout,
        sleeper=lambda _: None,
    )
    return {
        "events": len(result.events),
        "pages": result.pages_visited[:8],
        "blocked": len(result.blocked_by_robots),
        "errors": result.errors[:5],
    }


def _strict_agenda_probe(
    origin: str,
    robots: RobotFileParser,
    *,
    fetcher: Callable[..., Fetched],
    timeout: float,
) -> dict | None:
    """Try the usual Dutch agenda pages and require at least two strict events."""
    for path in AGENDA_PATHS:
        found = _agenda_page(urljoin(origin, path), robots, fetcher=fetcher, timeout=timeout)
        if found:
            return found
    return None


AGENDA_PATHS = ("agenda/", "evenementen/", "activiteiten/", "programma/", "voorstellingen/", "kalender/", "events/")


def _agenda_page(agenda_url: str, robots: RobotFileParser, *, fetcher: Callable[..., Fetched], timeout: float) -> dict | None:
    if not robots.can_fetch(USER_AGENT, agenda_url):
        return None
    try:
        page = fetcher(agenda_url, timeout=timeout)
    except Exception:
        return None
    if not (200 <= page.status < 300):
        return None
    if "html" not in page.content_type and "<html" not in page.text[:500].casefold():
        return None
    events = parse_agenda(page.text, agenda_url)
    if len(events) < 2:
        return None
    return {
        "url": agenda_url,
        "event_count": len(events),
        "sample_titles": [x.title for x in events[:5]],
    }


def probe_source(
    url: str,
    *,
    fetcher: Callable[..., Fetched] = default_fetch,
    timeout: float = 12,
    deep_pages: int = 0,
) -> ProbeResult:
    target = canonical_url(url)
    if not target:
        raise ValueError("url must be an absolute http(s) URL")
    parsed = urlparse(target)
    host = parsed.hostname or ""
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    robots, robots_loaded = _robots_for(target, fetcher, timeout)
    if not robots.can_fetch(USER_AGENT, target):
        return ProbeResult(target, host, "blocked", "blocked", [], None, {"robots": robots_loaded})

    extractors: list[str] = []
    details: dict = {"robots": robots_loaded}
    errors: list[str] = []

    try:
        page = fetcher(target, timeout=timeout)
        if 200 <= page.status < 300 and ("html" in page.content_type or "<html" in page.text[:500].casefold()):
            structured = parse_html(page.text, target)
            if structured:
                extractors.append("jsonld_event")
                details["jsonld_event_count_on_candidate_page"] = len(structured)
            parser = _CalendarLinkParser(target)
            parser.feed(page.text)
            if parser.ics_urls:
                extractors.append("ics")
                details["ics_urls"] = parser.ics_urls[:5]
        else:
            errors.append(f"candidate page HTTP {page.status}")
    except Exception as exc:
        errors.append(f"candidate page: {type(exc).__name__}: {exc}")

    tribe_url = wordpress_events_url(origin, page=1, per_page=1)
    if robots.can_fetch(USER_AGENT, tribe_url):
        try:
            feed = fetcher(tribe_url, timeout=timeout)
            if 200 <= feed.status < 300:
                payload = json.loads(feed.text)
                if isinstance(payload, dict) and isinstance(payload.get("events"), list):
                    extractors.insert(0, "wordpress_tribe")
                    details["wordpress_endpoint"] = tribe_url
        except Exception:
            pass

    if not extractors:
        agenda = _strict_agenda_probe(origin, robots, fetcher=fetcher, timeout=timeout)
        if agenda:
            extractors.append("html_agenda_dutch")
            details["html_agenda"] = agenda

    if not extractors and deep_pages > 0:
        try:
            shallow = _shallow_structured_probe(
                origin,
                fetcher=fetcher,
                timeout=timeout,
                max_pages=deep_pages,
            )
            details["shallow_site_probe"] = shallow
            if shallow["events"]:
                extractors.append("jsonld_event")
                details["jsonld_event_count_in_site_sample"] = shallow["events"]
        except Exception as exc:
            errors.append(f"shallow site probe: {type(exc).__name__}: {exc}")

    extractors = list(dict.fromkeys(extractors))
    preference = next(
        (x for x in ("wordpress_tribe", "jsonld_event", "ics", "html_agenda_dutch") if x in extractors),
        None,
    )
    return ProbeResult(
        url=target,
        host=host,
        robots_status="allowed",
        probe_status="supported" if extractors else "no_supported_extractor",
        extractors=extractors,
        suggested_extractor=preference,
        details=details,
        error="; ".join(errors) if errors else None,
    )


def _apply_probe(item: dict, result: ProbeResult) -> None:
    item["robotsStatus"] = result.robots_status
    item["probeStatus"] = result.probe_status
    item["extractor"] = result.suggested_extractor
    item["extractorsFound"] = result.extractors
    item["probeDetails"] = result.details
    item["lastError"] = result.error


def probe_queue(
    path: str | Path,
    *,
    limit: int = 10,
    workers: int = 5,
    fetcher: Callable[..., Fetched] = default_fetch,
    timeout: float = 12,
    deep_pages: int = 0,
) -> dict:
    """Probe independent candidate hosts concurrently, re-rank, and persist."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    candidates = payload.get("candidates", []) if isinstance(payload, dict) else []

    selected: list[tuple[int, dict]] = []
    for index, item in enumerate(candidates):
        if len(selected) >= max(0, limit):
            break
        if not isinstance(item, dict) or item.get("activationStatus") not in {None, "candidate"}:
            continue
        if item.get("policyStatus") == "blocked":
            continue
        if item.get("probeStatus") == "supported":
            continue
        selected.append((index, item))

    if selected:
        max_workers = max(1, min(int(workers or 1), 12, len(selected)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    probe_source,
                    item.get("url") or "",
                    fetcher=fetcher,
                    timeout=timeout,
                    deep_pages=deep_pages,
                ): index
                for index, item in selected
            }
            for future in as_completed(futures):
                index = futures[future]
                item = candidates[index]
                try:
                    _apply_probe(item, future.result())
                except Exception as exc:
                    item["probeStatus"] = "error"
                    item["lastError"] = f"{type(exc).__name__}: {exc}"

    for item in candidates:
        if isinstance(item, dict):
            item.update(candidate_priority(item))
    candidates.sort(
        key=lambda x: (-int(x.get("priorityScore") or 0), -int(x.get("score") or 0), x.get("host", ""))
        if isinstance(x, dict) else (0, 0, "")
    )

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump({"version": 1, "candidates": candidates}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return {"probed": len(selected), "queue_size": len(candidates), "candidates": candidates}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Probe candidate event-source websites without activating them")
    parser.add_argument("--queue", default="data/source_candidates.json")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--deep-pages", type=int, default=0, help="Sample event-prioritized site pages when the lead URL has no supported extractor")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    report = probe_queue(
        args.queue,
        limit=args.limit,
        workers=args.workers,
        timeout=args.timeout,
        deep_pages=args.deep_pages,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
