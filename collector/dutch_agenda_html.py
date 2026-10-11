"""Strict fallback extractor for Dutch organizer agenda pages.

This is deliberately narrower than a general text scraper. An item is emitted
only when its own heading block is followed by an explicit Dutch calendar date
WITH a year. We retain factual title/date/time/link fields only; descriptions
and images are never copied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import urljoin

MONTHS = {
    "januari": 1, "jan": 1,
    "februari": 2, "feb": 2,
    "maart": 3, "mrt": 3,
    "april": 4, "apr": 4,
    "mei": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "augustus": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_RE = re.compile(
    rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})\.?\s+(20\d{{2}})\b",
    re.I,
)
TIME_RE = re.compile(
    r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\s*(?:-|–|—|tot)\s*([01]?\d|2[0-3])[:.]([0-5]\d)\b",
    re.I,
)
# Single start times are accepted only with a clear temporal cue.
# Standalone numbers (addresses, ticket prices) must never become event times.
START_TIME_RE = re.compile(
    r"\b(?:vanaf|aanvang(?:stijd)?|start(?:tijd)?|begint(?:ijd)?|om)\s*:?\s*([01]?\d|2[0-3])[:.]([0-5]\d)\b",
    re.I,
)

_GENERIC_HEADINGS = {
    "agenda", "evenementen", "evenementen agenda", "kalender", "programma",
    "meer info", "meer informatie", "contact", "nieuws", "activiteiten",
}
_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "p", "li", "time", "a"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4"}


@dataclass(frozen=True)
class HtmlBlock:
    tag: str
    text: str
    href: str | None = None


@dataclass(frozen=True)
class AgendaEvent:
    title: str
    start_date: str
    time_text: str | None
    event_url: str | None


class _BlocksParser(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__()
        self.page_url = page_url
        self.stack: list[str] = []
        self.active: list[dict] = []
        self.href_stack: list[str | None] = []
        self.blocks: list[HtmlBlock] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self.stack.append(tag)
        attrs_dict = {str(k).lower(): v for k, v in attrs}
        current_href = self.href_stack[-1] if self.href_stack else None
        if tag == "a":
            href = attrs_dict.get("href")
            current_href = urljoin(self.page_url, str(href)) if href else None
        self.href_stack.append(current_href)
        if tag in _BLOCK_TAGS:
            self.active.append({
                "tag": tag,
                "depth": len(self.stack),
                "parts": [],
                "href": current_href,
            })

    def handle_data(self, data):
        if not data.strip():
            return
        for capture in self.active:
            capture["parts"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        depth = len(self.stack)
        finished = [x for x in self.active if x["tag"] == tag and x["depth"] == depth]
        for capture in finished:
            text = unescape(" ".join(capture["parts"]))
            text = " ".join(text.split()).strip()
            if text:
                self.blocks.append(HtmlBlock(capture["tag"], text, capture["href"]))
            self.active.remove(capture)
        if self.stack:
            self.stack.pop()
        if self.href_stack:
            self.href_stack.pop()


def extract_blocks(html: str, page_url: str) -> list[HtmlBlock]:
    parser = _BlocksParser(page_url)
    parser.feed(html)
    return parser.blocks


def parse_dutch_date(text: str) -> date | None:
    match = DATE_RE.search(unescape(text or ""))
    if not match:
        return None
    day = int(match.group(1))
    month = MONTHS[match.group(2).casefold().rstrip(".")]
    year = int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_time_range(text: str) -> str | None:
    value = unescape(text or "")
    match = TIME_RE.search(value)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)} – {int(match.group(3)):02d}:{match.group(4)}"
    start = START_TIME_RE.search(value)
    if start:
        return f"{int(start.group(1)):02d}:{start.group(2)}"
    return None


def _valid_title(value: str) -> bool:
    title = " ".join((value or "").split()).strip()
    if not 3 <= len(title) <= 140:
        return False
    if title.casefold() in _GENERIC_HEADINGS:
        return False
    if DATE_RE.fullmatch(title):
        return False
    return True


def _next_heading_index(blocks: list[HtmlBlock], index: int, limit: int) -> int:
    for j in range(index + 1, min(len(blocks), index + limit + 1)):
        if blocks[j].tag in _HEADING_TAGS:
            return j
    return min(len(blocks), index + limit + 1)


def parse_agenda(html: str, page_url: str, *, context_blocks: int = 8) -> list[AgendaEvent]:
    """Extract only heading-scoped events with their own following full date."""
    blocks = extract_blocks(html, page_url)
    out: list[AgendaEvent] = []
    seen: set[tuple[str, str, str]] = set()

    for i, block in enumerate(blocks):
        if block.tag not in _HEADING_TAGS or not _valid_title(block.text):
            continue

        end = _next_heading_index(blocks, i, max(2, context_blocks))
        forward = blocks[i + 1:end]

        date_index: int | None = None
        event_date: date | None = None
        date_text = ""
        for offset, nearby in enumerate(forward):
            parsed = parse_dutch_date(nearby.text)
            if parsed:
                event_date = parsed
                date_index = offset
                date_text = nearby.text
                break

        # Safety rule: never inherit a date from a previous event. Sites that put
        # the date before the title need a dedicated/container-aware adapter.
        if event_date is None:
            continue

        time_text = parse_time_range(date_text)
        if not time_text:
            for nearby in forward[(date_index + 1 if date_index is not None else 0):]:
                time_text = parse_time_range(nearby.text)
                if time_text:
                    break

        event_url = block.href
        if not event_url:
            for nearby in forward:
                if nearby.tag == "a" and nearby.href and (
                    "meer info" in nearby.text.casefold()
                    or "bekijk" in nearby.text.casefold()
                    or "details" in nearby.text.casefold()
                ):
                    event_url = nearby.href
                    break

        # Distinct matinee/evening performances are separate events.
        key = (block.text.casefold().strip(), event_date.isoformat(), time_text or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(AgendaEvent(
            title=block.text.strip(),
            start_date=event_date.isoformat(),
            time_text=time_text,
            event_url=event_url,
        ))

    return out
