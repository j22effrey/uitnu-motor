"""Independent first-party website crawler for UITNU.

The crawler is intentionally conservative:
- only crawls configured seed websites;
- respects robots.txt;
- prefers sitemap URLs and event-like paths;
- stays on the same site while crawling;
- extracts factual Schema.org Event JSON-LD;
- can use an explicitly approved strict Dutch agenda fallback;
- records promising external links as source-discovery candidates instead of
  automatically spidering the wider web;
- never copies long editorial descriptions or images.

This keeps UITNU useful without making the runtime dependent on a third-party
search or tourism API.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
import heapq
import json
import re
import time
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.error import HTTPError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from collector.dutch_agenda_html import AgendaEvent, parse_agenda
from collector.jsonld_events import StructuredEvent, parse_html
from pipeline.event_model import RawEvent

USER_AGENT = "UITNU-Crawler/0.1 (+first-party-event-discovery)"
MAX_RESPONSE_BYTES = 2_000_000

_EVENT_HINTS = (
    "agenda", "event", "events", "evenement", "evenementen", "programma",
    "activiteiten", "activiteit", "uitagenda", "kalender", "festival",
    "markt", "braderie", "kermis", "open-dag", "opendag", "fair", "expo",
    "tentoonstelling", "concert", "theater",
)
_NEGATIVE_HINTS = (
    "privacy", "cookie", "voorwaarden", "contact", "vacature", "login",
    "account", "winkelmand", "checkout", "wp-admin", "feed",
)


@dataclass(frozen=True)
class CrawlSource:
    id: str
    name: str
    root_url: str
    role: str = "organizer"  # organizer | venue | tourism | discovery
    enabled: bool = True
    max_pages: int = 40
    max_depth: int = 3
    min_delay_seconds: float = 0.35
    extractor_hint: str | None = None

    @classmethod
    def from_dict(cls, value: dict) -> "CrawlSource":
        return cls(
            id=str(value["id"]),
            name=str(value.get("name") or value["id"]),
            root_url=str(value.get("rootUrl") or value.get("root_url")),
            role=str(value.get("role") or "organizer"),
            enabled=bool(value.get("enabled", True)),
            max_pages=max(1, min(int(value.get("maxPages", 40)), 250)),
            max_depth=max(0, min(int(value.get("maxDepth", 3)), 8)),
            min_delay_seconds=max(0.0, min(float(value.get("minDelaySeconds", 0.35)), 10.0)),
            extractor_hint=(str(value.get("extractorHint") or value.get("extractor_hint") or "").strip() or None),
        )


@dataclass(frozen=True)
class Fetched:
    url: str
    status: int
    content_type: str
    text: str


@dataclass(frozen=True)
class ExternalCandidate:
    url: str
    from_url: str
    anchor_text: str
    score: int


@dataclass
class CrawlResult:
    events: list[RawEvent] = field(default_factory=list)
    pages_visited: list[str] = field(default_factory=list)
    external_candidates: list[ExternalCandidate] = field(default_factory=list)
    blocked_by_robots: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def asdict(self) -> dict:
        return {
            "events": [asdict(x) for x in self.events],
            "pages_visited": list(self.pages_visited),
            "external_candidates": [asdict(x) for x in self.external_candidates],
            "blocked_by_robots": list(self.blocked_by_robots),
            "errors": list(self.errors),
        }


def _clean_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme not in {"http", "https"} or not p.netloc:
        return ""
    return urlunparse((p.scheme, p.netloc.lower(), p.path or "/", p.params, p.query, ""))


def _host_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(seed_url: str, candidate_url: str) -> bool:
    return bool(_host_key(seed_url)) and _host_key(seed_url) == _host_key(candidate_url)


def event_link_score(url: str, anchor_text: str = "") -> int:
    hay = unescape(f"{url} {anchor_text}").casefold()
    score = 0
    for hint in _EVENT_HINTS:
        if hint in hay:
            score += 8
    for hint in _NEGATIVE_HINTS:
        if hint in hay:
            score -= 15
    path = urlparse(url).path.strip("/")
    if path:
        score += min(path.count("/") + 1, 4)
    if re.search(r"/20\d{2}/\d{1,2}/", path):
        score += 8
    return score


class _LinkParser(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__()
        self.page_url = page_url
        self.links: list[tuple[str, str]] = []
        self._active_href: str | None = None
        self._parts: list[str] = []
        self.no_follow = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = {str(k).lower(): v for k, v in attrs}
        if tag.lower() == "meta":
            if (attrs_dict.get("name") or "").lower() == "robots":
                content = (attrs_dict.get("content") or "").lower()
                if "nofollow" in content:
                    self.no_follow = True
            return
        if tag.lower() != "a":
            return
        href = attrs_dict.get("href")
        if not href:
            return
        href = str(href).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            return
        self._active_href = href
        self._parts = []

    def handle_data(self, data):
        if self._active_href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._active_href is None:
            return
        url = _clean_url(urljoin(self.page_url, self._active_href))
        if url:
            text = " ".join(" ".join(self._parts).split())
            self.links.append((url, text))
        self._active_href = None
        self._parts = []


def extract_links(html: str, page_url: str) -> tuple[list[tuple[str, str]], bool]:
    parser = _LinkParser(page_url)
    parser.feed(html)
    return parser.links, parser.no_follow


def parse_robots_sitemaps(text: str, root_url: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        if not line.lower().startswith("sitemap:"):
            continue
        value = _clean_url(urljoin(root_url, line.split(":", 1)[1].strip()))
        if value and value not in out:
            out.append(value)
    return out


def parse_sitemap(text: str, base_url: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, nested_sitemaps) from a sitemap XML document."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return [], []
    local_name = root.tag.rsplit("}", 1)[-1].lower()
    locs: list[str] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() != "loc":
            continue
        if not node.text:
            continue
        url = _clean_url(urljoin(base_url, node.text.strip()))
        if url:
            locs.append(url)
    if local_name == "sitemapindex":
        return [], locs
    return locs, []


class _SameSiteRedirectHandler(HTTPRedirectHandler):
    """Refuse redirects to any unapproved domain or an insecure scheme."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from_url = req.full_url
        if not same_site(from_url, newurl):
            return None
        if urlparse(from_url).scheme == "https" and urlparse(newurl).scheme != "https":
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_fetch(url: str, *, timeout: float = 15) -> Fetched:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
        },
    )
    with build_opener(_SameSiteRedirectHandler()).open(req, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError(f"response too large: {url}")
        content_type = (response.headers.get_content_type() or "").lower()
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, "replace")
        return Fetched(
            url=_clean_url(response.geturl()) or url,
            status=int(getattr(response, "status", 200)),
            content_type=content_type,
            text=text,
        )


def _load_robots(root_url: str, fetcher: Callable[..., Fetched], *, timeout: float) -> tuple[RobotFileParser, list[str]]:
    p = urlparse(root_url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        fetched = fetcher(robots_url, timeout=timeout)
        if not same_site(root_url, fetched.url):
            rp.disallow_all = True
            return rp, []
        if 200 <= fetched.status < 300:
            # A login/anti-bot HTML response is not a valid robots policy.
            if "html" in fetched.content_type.lower():
                rp.disallow_all = True
                return rp, []
            rp.parse(fetched.text.splitlines())
            return rp, parse_robots_sitemaps(fetched.text, root_url)
        if fetched.status in (404, 410):
            rp.parse([])  # Explicitly absent robots.txt permits crawling.
            return rp, []
    except HTTPError as exc:
        if exc.code in (404, 410):
            rp.parse([])  # urllib raises for missing robots.txt.
            return rp, []
    except Exception:
        pass
    # 401, 403, 5xx and network errors are not evidence of permission.
    rp.disallow_all = True
    return rp, []


def _structured_to_raw(source: CrawlSource, item: StructuredEvent, page_url: str) -> RawEvent | None:
    if not item.title or not item.start:
        return None
    address = " ".join(x for x in (item.street, item.postal_code) if x) or None
    trusted_first_party = source.role in {"organizer", "venue"}
    return RawEvent(
        source_name=source.name,
        source_type="structured_web" if trusted_first_party else "discovery_web",
        source_url=item.event_url or item.source_url or page_url,
        source_id=None,
        title=item.title,
        start_at=item.start,
        end_at=item.end,
        venue=item.venue,
        address=address,
        city=item.city,
        lat=item.latitude,
        lon=item.longitude,
        category=None,
        price_text=item.price,
        verification_status="organizer_confirmed" if trusted_first_party else "unknown",
        raw={
            "source": "first_party_crawler",
            "seed": source.root_url,
            "page_url": page_url,
            "role": source.role,
        },
    )


def _agenda_to_raw(source: CrawlSource, item: AgendaEvent, page_url: str) -> RawEvent:
    trusted_first_party = source.role in {"organizer", "venue"}
    start_at = item.start_date
    end_at = None
    if item.time_text:
        times = re.findall(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", item.time_text)
        if times:
            start_at = f"{item.start_date}T{times[0]}:00"
        if len(times) >= 2:
            # 20:00–01:00 ends the following day, not before it starts.
            end_date = date.fromisoformat(item.start_date)
            if times[1] < times[0]:
                end_date += timedelta(days=1)
            end_at = f"{end_date.isoformat()}T{times[1]}:00"
    return RawEvent(
        source_name=source.name,
        source_type="structured_web" if trusted_first_party else "discovery_web",
        source_url=item.event_url or page_url,
        source_id=None,
        title=item.title,
        start_at=start_at,
        end_at=end_at,
        venue=None,
        address=None,
        city=None,
        lat=None,
        lon=None,
        category=None,
        price_text=None,
        verification_status="organizer_confirmed" if trusted_first_party else "unknown",
        raw={
            "source": "html_agenda_dutch",
            "seed": source.root_url,
            "page_url": page_url,
            "role": source.role,
            "time_text": item.time_text,
        },
    )


def _candidate_score(url: str, anchor: str) -> int:
    score = event_link_score(url, anchor)
    host = _host_key(url)
    if host.endswith((".nl", ".com", ".org")):
        score += 3
    if any(x in anchor.casefold() for x in ("officiële", "website", "organisator", "locatie")):
        score += 15
    return score


def _dedupe_external(values: Iterable[ExternalCandidate]) -> list[ExternalCandidate]:
    best: dict[str, ExternalCandidate] = {}
    for item in values:
        host = _host_key(item.url)
        if not host:
            continue
        previous = best.get(host)
        if previous is None or item.score > previous.score:
            best[host] = item
    return sorted(best.values(), key=lambda x: (-x.score, x.url))


def _append_event(result: CrawlResult, event_keys: set[tuple], raw: RawEvent) -> None:
    key = (
        raw.title.casefold().strip(),
        raw.start_at,
        (raw.venue or "").casefold().strip(),
        (raw.city or "").casefold().strip(),
    )
    if key in event_keys:
        return
    event_keys.add(key)
    result.events.append(raw)


def crawl_source(
    source: CrawlSource,
    *,
    fetcher: Callable[..., Fetched] = default_fetch,
    timeout: float = 15,
    sleeper: Callable[[float], None] = time.sleep,
) -> CrawlResult:
    if not source.enabled:
        return CrawlResult()
    root = _clean_url(source.root_url)
    if not root:
        raise ValueError("root_url must be an absolute http(s) URL")

    result = CrawlResult()
    robots, sitemap_urls = _load_robots(root, fetcher, timeout=timeout)
    if robots.disallow_all:
        result.errors.append("robots_unavailable_or_denied")
        return result
    root_origin = f"{urlparse(root).scheme}://{urlparse(root).netloc}"

    fallback_sitemap = root_origin + "/sitemap.xml"
    if fallback_sitemap not in sitemap_urls:
        sitemap_urls.append(fallback_sitemap)

    discovered_pages: list[str] = []
    seen_sitemaps: set[str] = set()
    sitemap_queue = list(sitemap_urls[:5])
    while sitemap_queue and len(seen_sitemaps) < 12:
        sitemap_url = sitemap_queue.pop(0)
        if sitemap_url in seen_sitemaps or not same_site(root, sitemap_url):
            continue
        seen_sitemaps.add(sitemap_url)
        if not robots.can_fetch(USER_AGENT, sitemap_url):
            result.blocked_by_robots.append(sitemap_url)
            continue
        try:
            fetched = fetcher(sitemap_url, timeout=timeout)
            if not same_site(root, fetched.url):
                result.errors.append(f"{sitemap_url}: redirected_off_site")
                continue
            if not (200 <= fetched.status < 300):
                continue
            pages, nested = parse_sitemap(fetched.text, fetched.url)
            discovered_pages.extend(x for x in pages if same_site(root, x))
            sitemap_queue.extend(x for x in nested if same_site(root, x))
        except Exception:
            continue

    frontier: list[tuple[int, int, int, str]] = []
    serial = 0

    def push(url: str, depth: int, anchor: str = ""):
        nonlocal serial
        url = _clean_url(url)
        if not url or not same_site(root, url) or depth > source.max_depth:
            return
        serial += 1
        heapq.heappush(frontier, (-event_link_score(url, anchor), depth, serial, url))

    push(root, 0)
    if source.extractor_hint == "html_agenda_dutch":
        push(root_origin + "/agenda/", 0, "agenda evenementen")
    for url in discovered_pages[:2000]:
        push(url, 1)

    visited: set[str] = set()
    event_keys: set[tuple] = set()
    external: list[ExternalCandidate] = []

    while frontier and len(result.pages_visited) < source.max_pages:
        _, depth, _, url = heapq.heappop(frontier)
        if url in visited:
            continue
        visited.add(url)

        if not robots.can_fetch(USER_AGENT, url):
            result.blocked_by_robots.append(url)
            continue

        try:
            fetched = fetcher(url, timeout=timeout)
        except Exception as exc:
            result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
            continue
        if not (200 <= fetched.status < 300):
            result.errors.append(f"{url}: HTTP {fetched.status}")
            continue
        if "html" not in fetched.content_type and "<html" not in fetched.text[:500].casefold():
            continue

        page_url = _clean_url(fetched.url)
        if not page_url or not same_site(root, page_url):
            result.errors.append(f"{url}: redirected_off_site")
            continue
        if not robots.can_fetch(USER_AGENT, page_url):
            result.blocked_by_robots.append(page_url)
            continue
        result.pages_visited.append(page_url)

        for item in parse_html(fetched.text, page_url):
            raw = _structured_to_raw(source, item, page_url)
            if raw is not None:
                _append_event(result, event_keys, raw)

        if source.extractor_hint == "html_agenda_dutch" and "agenda" in urlparse(page_url).path.casefold():
            for item in parse_agenda(fetched.text, page_url):
                _append_event(result, event_keys, _agenda_to_raw(source, item, page_url))

        links, no_follow = extract_links(fetched.text, page_url)
        if not no_follow and depth < source.max_depth:
            for link, anchor in links:
                if same_site(root, link):
                    push(link, depth + 1, anchor)
                else:
                    score = _candidate_score(link, anchor)
                    if score >= 10:
                        external.append(ExternalCandidate(
                            url=link,
                            from_url=page_url,
                            anchor_text=anchor[:180],
                            score=score,
                        ))

        if source.min_delay_seconds and frontier:
            sleeper(source.min_delay_seconds)

    result.external_candidates = _dedupe_external(external)[:100]
    return result


def load_sources(path: str) -> list[CrawlSource]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    values = payload.get("sources") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ValueError("crawler source file must contain a 'sources' list")
    return [CrawlSource.from_dict(x) for x in values if isinstance(x, dict)]


def crawl_many(
    sources: Iterable[CrawlSource],
    *,
    fetcher: Callable[..., Fetched] = default_fetch,
    timeout: float = 15,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, CrawlResult]:
    return {
        source.id: crawl_source(source, fetcher=fetcher, timeout=timeout, sleeper=sleeper)
        for source in sources
        if source.enabled
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl configured first-party event websites")
    parser.add_argument(
        "--sources",
        default="collector/web_crawl_sources.json",
        help="JSON file with crawler seed websites",
    )
    parser.add_argument("--source-id", help="Only crawl one configured source")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    sources = load_sources(args.sources)
    if args.source_id:
        sources = [x for x in sources if x.id == args.source_id]
        if not sources:
            raise SystemExit(f"unknown source id: {args.source_id}")

    results = crawl_many(sources)
    payload = {key: value.asdict() for key, value in results.items()}
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
