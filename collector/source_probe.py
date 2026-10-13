"""Safely probe source candidates for extraction methods UITNU already supports.

Probing does not activate a source. It records technical capability only:
WordPress/The Events Calendar, Schema.org Event JSON-LD, ICS, or UITNU's strict
Dutch HTML agenda fallback.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from collector.dutch_agenda_html import parse_agenda
from collector.jsonld_events import parse_html
from collector.site_crawler import CrawlSource, Fetched, USER_AGENT, crawl_source, default_fetch, same_site
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


# Versie van de test. Wordt de test beter, dan komen websites die eerder 'niet leesbaar' waren
# (of door een storing of een ontbrekende robots.txt 'geblokkeerd') vanzelf opnieuw aan de beurt.
PROBE_VERSION = 3
# Na zoveel dagen een website opnieuw testen (agenda's veranderen, sites worden vernieuwd).
RETRY_DAYS = {"no_supported_extractor": 21, "error": 3, "blocked": 30}


class _AgendaLinkParser(HTMLParser):
    """Links op de voorpagina naar de agenda, ook als die niet op /agenda/ staat."""

    WORDS = re.compile(r"agenda|evenement|activiteit|programma|voorstelling|kalender|events?\b|"
                       r"wat[ -]is[ -]er[ -]te[ -]doen|uitagenda|concerten|optredens|tentoonstelling", re.I)
    SKIP = re.compile(r"\.(?:pdf|jpe?g|png|gif|docx?|zip)(?:$|\?)|^(?:mailto|tel|javascript):", re.I)

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.host = (urlparse(base_url).hostname or "").removeprefix("www.")
        self.links: list[str] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict((str(k).lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._href is None:
            return
        href, text = self._href.strip(), " ".join(" ".join(self._text).split())
        self._href = None
        if not href or self.SKIP.search(href):
            return
        url = canonical_url(urljoin(self.base_url, href))
        parsed = urlparse(url or "")
        if not url or (parsed.hostname or "").removeprefix("www.") != self.host:
            return
        if (self.WORDS.search(parsed.path) or self.WORDS.search(text)) and url not in self.links:
            self.links.append(url)


_SOFT_REDIRECT = re.compile(
    r"""(?:window\.location(?:\.href)?|document\.location(?:\.href)?|location\.replace\()\s*=?\s*["']([^"']+)["']"""
    r"""|<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["'][^"']*?url\s*=\s*([^"'>\s]+)""", re.I)


def soft_redirect(html: str, page_url: str) -> str | None:
    """Een kleine voorpagina die met een script of meta-tag doorstuurt (bijv. naar /wp/)."""
    if not html or len(html) > 4000:
        return None
    match = _SOFT_REDIRECT.search(html)
    if not match:
        return None
    target = canonical_url(urljoin(page_url, (match.group(1) or match.group(2) or "").strip()))
    if not target or not same_site(page_url, target):
        return None
    # Zelfde website via http: dan via https, zoals de pagina zelf.
    if target.startswith("http://") and page_url.startswith("https://"):
        target = "https://" + target[len("http://"):]
    return target if target.rstrip("/") != canonical_url(page_url).rstrip("/") else None


def agenda_links(html: str, base_url: str, limit: int = 4) -> list[str]:
    parser = _AgendaLinkParser(base_url)
    try:
        parser.feed(html)
    except Exception:
        return []
    # Kortste adressen eerst: '/agenda' gaat voor '/agenda/2026/concert-x'.
    return sorted(parser.links, key=lambda u: (u.count("/"), len(u)))[:limit]


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
    """robots.txt lezen, net als de crawler (collector/site_crawler.py):
    - 'loaded': er is een robots.txt en die geldt;
    - 'absent': geen robots.txt (404/410): dan mag alles (zo is de afspraak, RFC 9309);
    - 'invalid': een webpagina in plaats van robots.txt, of doorgestuurd naar een andere site: niets;
    - 'unavailable': niet bereikbaar (storing): nu niets, later opnieuw proberen."""
    p = urlparse(url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        fetched = fetcher(robots_url, timeout=timeout)
        if fetched.url and not same_site(url, fetched.url):
            rp.parse(["User-agent: *", "Disallow: /"])
            return rp, "invalid"
        if 200 <= fetched.status < 300:
            if "html" in (fetched.content_type or "").lower():
                rp.parse(["User-agent: *", "Disallow: /"])
                return rp, "invalid"
            rp.parse(fetched.text.splitlines())
            return rp, "loaded"
        if fetched.status in (404, 410):
            rp.parse([])
            return rp, "absent"
    except HTTPError as exc:
        if exc.code in (404, 410):
            rp.parse([])  # urllib meldt een ontbrekende robots.txt als fout
            return rp, "absent"
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


def _upcoming(events: list, today: date | None) -> list:
    """Alleen uitjes die nog komen: een nieuwspagina (titels met de datum van gisteren) is geen agenda."""
    day = (today or date.today()).isoformat()
    return [e for e in events if str(getattr(e, "start_date", "") or "") >= day]


def _strict_agenda_probe(
    origin: str,
    robots: RobotFileParser,
    *,
    fetcher: Callable[..., Fetched],
    timeout: float,
    home_html: str | None = None,
    home_url: str | None = None,
    today: date | None = None,
) -> dict | None:
    """Try the agenda pages the site itself links to, the home page, and the usual Dutch
    agenda paths; require at least two strict upcoming events."""
    tried: set[str] = set()
    if home_html and home_url:
        events = _upcoming(parse_agenda(home_html, home_url), today)
        if len(events) >= 2:
            return {"url": home_url, "event_count": len(events), "sample_titles": [x.title for x in events[:5]]}
        tried.add(canonical_url(home_url) or home_url)
        for url in agenda_links(home_html, home_url):
            tried.add(url)
            found = _agenda_page(url, robots, fetcher=fetcher, timeout=timeout, today=today)
            if found:
                return found
    for path in AGENDA_PATHS:
        url = urljoin(origin, path)
        if url in tried:
            continue
        found = _agenda_page(url, robots, fetcher=fetcher, timeout=timeout, today=today)
        if found:
            return found
    return None


AGENDA_PATHS = ("agenda/", "evenementen/", "activiteiten/", "programma/", "voorstellingen/", "kalender/", "events/",
                "dorpsagenda/", "activiteitenkalender/")


def _agenda_page(agenda_url: str, robots: RobotFileParser, *, fetcher: Callable[..., Fetched], timeout: float,
                 today: date | None = None) -> dict | None:
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
    events = _upcoming(parse_agenda(page.text, agenda_url), today)
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
    today: date | None = None,
) -> ProbeResult:
    target = canonical_url(url)
    if not target:
        raise ValueError("url must be an absolute http(s) URL")
    parsed = urlparse(target)
    host = parsed.hostname or ""
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    robots, robots_loaded = _robots_for(target, fetcher, timeout)
    if robots_loaded == "unavailable":
        # Storing, geen verbod: binnenkort opnieuw proberen.
        return ProbeResult(target, host, "unavailable", "error", [], None, {"robots": robots_loaded},
                           "robots.txt niet bereikbaar")
    if not robots.can_fetch(USER_AGENT, target):
        return ProbeResult(target, host, "blocked", "blocked", [], None, {"robots": robots_loaded})

    extractors: list[str] = []
    details: dict = {"robots": robots_loaded}
    errors: list[str] = []
    home_html: str | None = None
    home_url = target

    try:
        page = fetcher(target, timeout=timeout)
        redirect = soft_redirect(page.text, page.url or target) if 200 <= page.status < 300 else None
        if redirect and robots.can_fetch(USER_AGENT, redirect):
            details["redirect"] = redirect
            page = fetcher(redirect, timeout=timeout)
        if 200 <= page.status < 300 and ("html" in page.content_type or "<html" in page.text[:500].casefold()):
            home_html, home_url = page.text, (canonical_url(page.url) or target)
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
                # Een lege lijst bewijst niets: dan levert de bron (nu) geen uitjes.
                if isinstance(payload, dict) and isinstance(payload.get("events"), list) and payload["events"]:
                    extractors.insert(0, "wordpress_tribe")
                    details["wordpress_endpoint"] = tribe_url
        except Exception:
            pass

    if not extractors:
        agenda = _strict_agenda_probe(origin, robots, fetcher=fetcher, timeout=timeout,
                                      home_html=home_html, home_url=home_url, today=today)
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


def _apply_probe(item: dict, result: ProbeResult, today: str | None = None) -> None:
    item["robotsStatus"] = result.robots_status
    item["probeStatus"] = result.probe_status
    item["extractor"] = result.suggested_extractor
    item["extractorsFound"] = result.extractors
    item["probeDetails"] = result.details
    item["lastError"] = result.error
    item["probedAt"] = today or date.today().isoformat()
    item["probeVersion"] = PROBE_VERSION


def _retest_with_new_version(item: dict) -> bool:
    """Eerder afgewezen door een oudere versie van de test, om een reden die de nieuwe versie beter doet."""
    if int(item.get("probeVersion") or 1) >= PROBE_VERSION:
        return False
    status = item.get("probeStatus")
    robots = (item.get("probeDetails") or {}).get("robots") if isinstance(item.get("probeDetails"), dict) else None
    return status in ("no_supported_extractor", "error") or (status == "blocked" and robots == "unavailable")


def probe_due(item: dict, today: date) -> bool:
    """Moet deze website (opnieuw) getest worden?

    Nog nooit getest: ja. Eerder niet leesbaar met een oudere versie van de test: ja.
    Anders pas na een wachttijd, zodat elke ronde vooral nieuwe websites aan de beurt komen."""
    if not isinstance(item, dict) or item.get("activationStatus") not in {None, "candidate"}:
        return False
    if item.get("policyStatus") == "blocked" or item.get("areaStatus") == "buiten":
        return False
    status = item.get("probeStatus")
    if status in (None, "", "pending"):
        return True
    if status == "supported":
        return False
    if _retest_with_new_version(item):
        return True
    # Een nieuwe tip van de eigenaar: één keer opnieuw testen, ook als het kort geleden nog niet lukte.
    tips = [str(e.get("seenAt") or "")[:10] for e in item.get("evidence") or []
            if isinstance(e, dict) and e.get("kind") == "tip"]
    if tips and str(item.get("probedAt") or "") < max(tips):
        return True
    try:
        age = (today - date.fromisoformat(str(item.get("probedAt")))).days
    except ValueError:
        return False  # getest voordat de datum werd bijgehouden: wacht op de volgende versie
    return age >= RETRY_DAYS.get(str(status), 21)


def probe_queue(
    path: str | Path,
    *,
    limit: int = 10,
    workers: int = 5,
    fetcher: Callable[..., Fetched] = default_fetch,
    timeout: float = 12,
    deep_pages: int = 0,
    today: str | None = None,
    budget_seconds: float | None = None,
) -> dict:
    """Probe independent candidate hosts concurrently, re-rank, and persist.

    With a time budget it stops waiting when time is up and still saves everything that was
    tested; the rest simply comes first next round."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    candidates = payload.get("candidates", []) if isinstance(payload, dict) else []

    day = date.fromisoformat(today) if today else date.today()
    due = [(index, item) for index, item in enumerate(candidates) if probe_due(item, day)]
    # Volgorde: tips van de eigenaar; nieuw gevonden dorpswebsites; websites die een oudere test
    # onterecht afwees (vaak de belangrijkste plekken); nieuwe websites van gemeenten en festivals
    # (uit Wikidata: daar staan de grote evenementen); andere nog nooit geteste websites; dan
    # herkansingen na de wachttijd. Binnen elke groep in de volgorde van de wachtrij.
    def rank(entry: tuple[int, dict]) -> tuple[int, int]:
        index, item = entry
        kinds = {e.get("kind") for e in item.get("evidence") or [] if isinstance(e, dict)}
        fresh = item.get("probeStatus") in (None, "", "pending")
        group = (0 if "tip" in kinds else 1 if "dorpssite" in kinds and fresh
                 else 2 if _retest_with_new_version(item) else 3 if "wikidata" in kinds and fresh
                 else 4 if fresh else 5)
        return (group, index)
    selected = sorted(due, key=rank)[:max(0, limit)]

    finished = 0
    if selected:
        max_workers = max(1, min(int(workers or 1), 12, len(selected)))
        pool = ThreadPoolExecutor(max_workers=max_workers)
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
        try:
            for future in as_completed(futures, timeout=budget_seconds):
                index = futures[future]
                item = candidates[index]
                finished += 1
                try:
                    _apply_probe(item, future.result(), day.isoformat())
                except Exception as exc:
                    item["probeStatus"] = "error"
                    item["lastError"] = f"{type(exc).__name__}: {exc}"
                    item["probedAt"] = day.isoformat()
                    item["probeVersion"] = PROBE_VERSION
        except FuturesTimeout:
            pass  # tijd op: wat nog niet klaar is, komt de volgende ronde als eerste
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

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
    return {"probed": finished, "selected": len(selected), "queue_size": len(candidates), "candidates": candidates}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Probe candidate event-source websites without activating them")
    parser.add_argument("--queue", default="data/source_candidates.json")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--deep-pages", type=int, default=0, help="Sample event-prioritized site pages when the lead URL has no supported extractor")
    parser.add_argument("--budget-minutes", type=float, default=None, help="stop na zoveel minuten (en bewaar wat er is)")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--summary", action="store_true", help="alleen een kort verslag tonen")
    args = parser.parse_args()
    report = probe_queue(
        args.queue,
        limit=args.limit,
        workers=args.workers,
        timeout=args.timeout,
        deep_pages=args.deep_pages,
        budget_seconds=args.budget_minutes * 60 if args.budget_minutes else None,
    )
    if args.summary:
        from collections import Counter
        statuses = Counter(str(c.get("probeStatus")) for c in report["candidates"] if isinstance(c, dict))
        print(f"Getest: {report['probed']} van {report['selected']} gekozen websites "
              f"(wachtrij: {report['queue_size']}). Stand: {dict(statuses.most_common())}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
