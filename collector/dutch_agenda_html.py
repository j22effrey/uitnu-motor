"""Strict fallback extractor for Dutch organizer agenda pages.

This is deliberately narrower than a general text scraper. An item is emitted
only when its own heading block has an explicit calendar date: a Dutch date WITH
a year ('17 oktober 2026'), a numeric or ISO date ('17-10-2026', <time datetime>),
or a date without a year whose weekday proves the year ('za 17 okt').
On pages built from cards (one event per <article>, <li> or <div>), the date may
also stand before the title, as long as it is in the same card.
We retain factual title/date/time/link fields only; descriptions and images are
never copied.
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
NUMERIC_DATE_RE = re.compile(r"(?<![\d.:/-])(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})(?![\d])")
ISO_DATE_RE = re.compile(r"(?<![\d-])(20\d{2})-(\d{2})-(\d{2})(?![\d])")
WEEKDAYS = {
    "maandag": 0, "ma": 0, "dinsdag": 1, "di": 1, "woensdag": 2, "wo": 2, "donderdag": 3, "do": 3,
    "vrijdag": 4, "vr": 4, "zaterdag": 5, "za": 5, "zondag": 6, "zo": 6,
}
WEEKDAY_PATTERN = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
# 'zaterdag 17 oktober' of 'za 17 okt': zonder jaar, maar de weekdag bewijst welk jaar het is.
YEARLESS_RE = re.compile(
    rf"\b({WEEKDAY_PATTERN})\.?,?\s+(\d{{1,2}})\s+({MONTH_PATTERN})\b\.?",
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
    # Kopjes boven een groep uitjes of op de rest van de pagina: geen naam van een uitje.
    "concerten", "muziek", "theater", "voorstellingen", "exposities", "tentoonstellingen", "lezingen",
    "workshops", "cursussen", "films", "film", "markten", "kinderen", "jeugd", "familie", "sport",
    "komende activiteiten", "komende evenementen", "komende voorstellingen", "binnenkort", "uitgelicht",
    "vandaag", "morgen", "deze week", "dit weekend", "volgende week", "later", "archief", "afgelopen",
    "eerdere activiteiten", "nieuwsbrief", "over ons", "sponsors", "partners", "volg ons", "route",
    "openingstijden", "tickets", "kaartverkoop", "praktische informatie", "zoeken", "categorieën",
    "categorie", "tags", "delen", "menu", "navigatie", "adres", "locatie", "prijzen", "info",
}
# Kopjes op agendapagina's die geen uitje zijn: vragen, opsommingen, knoppen en oproepen.
_NAVIGATION_TITLE = re.compile(
    r"(?:[?:]$|^(?:…|\.\.\.)|^(?:meld je aan|schrijf je in|bekijk|lees meer|delen|deel dit|andere steun|nieuwsbrief)\b)",
    re.I,
)
_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "p", "li", "time", "a", "span", "div", "td", "dt", "dd", "strong"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4"}
# Elementen zonder sluittag: die tellen niet mee bij het bijhouden van de nesting.
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
              "source", "track", "wbr"}


@dataclass(frozen=True)
class HtmlBlock:
    tag: str
    text: str
    href: str | None = None
    ancestors: tuple[int, ...] = ()   # ids van de omliggende elementen, van buiten naar binnen
    element: int = -1                  # id van het element zelf


@dataclass(frozen=True)
class AgendaEvent:
    title: str
    start_date: str
    time_text: str | None
    event_url: str | None


class _BlocksParser(HTMLParser):
    """Zet de pagina om in tekstblokken, met per blok de omliggende elementen.

    Robuust voor elementen zonder sluittag (<br>, <img>) en voor vergeten sluittags:
    een sluittag sluit alles wat erbinnen nog openstond."""

    def __init__(self, page_url: str):
        super().__init__()
        self.page_url = page_url
        self.stack: list[dict] = []
        self.blocks: list[HtmlBlock] = []
        self._next_id = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _VOID_TAGS:
            if tag == "br":
                self.handle_data(" ")
            return
        attrs_dict = {str(k).lower(): v for k, v in attrs}
        href = self.stack[-1]["href"] if self.stack else None
        if tag == "a":
            value = attrs_dict.get("href")
            href = urljoin(self.page_url, str(value)) if value else None
        self._next_id += 1
        self.stack.append({
            "tag": tag,
            "id": self._next_id,
            "href": href,
            "capture": tag in _BLOCK_TAGS,
            "parts": [],
            "datetime": str(attrs_dict.get("datetime") or "") if tag == "time" else "",
        })

    def handle_startendtag(self, tag, attrs):
        if tag.lower() in _VOID_TAGS:
            self.handle_starttag(tag, attrs)
        else:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not data.strip() and data != " ":
            return
        for element in self.stack:
            if element["capture"]:
                element["parts"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _VOID_TAGS:
            return
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i]["tag"] == tag), None)
        if index is None:
            return  # sluittag zonder begin: negeren
        while len(self.stack) > index:
            element = self.stack.pop()
            if not element["capture"]:
                continue
            text = unescape(" ".join(element["parts"]))
            if element["datetime"]:
                text = f"{text} {element['datetime']}"
            text = " ".join(text.split()).strip()
            if text:
                self.blocks.append(HtmlBlock(element["tag"], text, element["href"],
                                             tuple(e["id"] for e in self.stack), element["id"]))

    def close(self):
        super().close()
        while self.stack:
            self.handle_endtag(self.stack[-1]["tag"])


def extract_blocks(html: str, page_url: str) -> list[HtmlBlock]:
    parser = _BlocksParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.blocks


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_dutch_date(text: str, today: date | None = None) -> date | None:
    """Een datum met jaar, of zonder jaar als de weekdag het jaar bewijst."""
    value = unescape(text or "")
    match = DATE_RE.search(value)
    if match:
        return _safe_date(int(match.group(3)), MONTHS[match.group(2).casefold().rstrip(".")], int(match.group(1)))
    match = ISO_DATE_RE.search(value)
    if match:
        found = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found:
            return found
    match = NUMERIC_DATE_RE.search(value)
    if match:
        found = _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if found:
            return found
    match = YEARLESS_RE.search(value)
    if match:
        today = today or date.today()
        weekday = WEEKDAYS[match.group(1).casefold()]
        month = MONTHS[match.group(3).casefold().rstrip(".")]
        for year in (today.year, today.year + 1, today.year - 1):
            found = _safe_date(year, month, int(match.group(2)))
            if found and found.weekday() == weekday and abs((found - today).days) <= 300:
                return found
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


_HEADING_TAGS_RANK = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
_DATE_WORDS = re.compile(
    rf"\b(?:{WEEKDAY_PATTERN}|{MONTH_PATTERN}|vandaag|morgen|uur)\b\.?|[\d:./-]+", re.I)


def _date_only(value: str) -> bool:
    """Een kopje dat alleen een datum is ('zaterdag 17 oktober'), geen naam van een uitje."""
    rest = _DATE_WORDS.sub(" ", value or "")
    return len(re.sub(r"[^a-zA-Z]", "", rest)) < 3


def _valid_title(value: str) -> bool:
    title = " ".join((value or "").split()).strip()
    if not 3 <= len(title) <= 140:
        return False
    if title.casefold() in _GENERIC_HEADINGS:
        return False
    if DATE_RE.fullmatch(title) or _date_only(title):
        return False
    if _NAVIGATION_TITLE.search(title):
        return False
    return True


def _next_heading_index(blocks: list[HtmlBlock], index: int, limit: int, skip: set[int] = frozenset()) -> int:
    for j in range(index + 1, min(len(blocks), index + limit + 1)):
        if blocks[j].tag in _HEADING_TAGS and j not in skip:
            return j
    return min(len(blocks), index + limit + 1)


def _count(blocks: list[HtmlBlock], headings: list[int]) -> dict[int, int]:
    count: dict[int, int] = {}
    for i in headings:
        for element in blocks[i].ancestors:
            count[element] = count.get(element, 0) + 1
    return count


def _subtitles(blocks: list[HtmlBlock], headings: list[int], today: date | None) -> set[int]:
    """Ondertitels: een kleiner kopje direct onder de titel, samen met alleen die titel in
    hetzelfde element ('<h3>Wende</h3><h4>Nieuwe show</h4>'). Dat is geen apart uitje."""
    count = _count(blocks, headings)
    out = set()
    for a, b in zip(headings, headings[1:]):
        first, second = blocks[a], blocks[b]
        if _HEADING_TAGS_RANK[second.tag] <= _HEADING_TAGS_RANK[first.tag]:
            continue
        if not first.ancestors or first.ancestors[-1:] != second.ancestors[-1:] or count.get(first.ancestors[-1]) != 2:
            continue
        if any(parse_dutch_date(x.text, today) for x in blocks[a + 1:b]):
            continue
        out.add(b)
    return out


def _cards(blocks: list[HtmlBlock], headings: list[int]) -> dict[int, int]:
    """Per kop (index) het kaartje waar hij in staat: het grootste omliggende element met
    maar één uitje-kop erin. Lijsten met meerdere uitjes zijn dus nooit één kaartje."""
    count = _count(blocks, headings)
    cards = {}
    for i in headings:
        ancestors = blocks[i].ancestors
        card = next((element for element in ancestors if count.get(element) == 1), None)
        # De hele pagina is geen kaartje (een pagina over één uitje): dan gewoon vooruit zoeken.
        if card is not None and card != ancestors[0]:
            cards[i] = card
    return cards


def parse_agenda(html: str, page_url: str, *, context_blocks: int = 16, today: date | None = None) -> list[AgendaEvent]:
    """Extract only heading-scoped events with their own full date."""
    blocks = extract_blocks(html, page_url)
    headings = [i for i, b in enumerate(blocks) if b.tag in _HEADING_TAGS and _valid_title(b.text)]
    subtitles = _subtitles(blocks, headings, today)
    cards = _cards(blocks, [i for i in headings if i not in subtitles])
    card_ids = set(cards.values())
    out: list[AgendaEvent] = []
    seen: set[tuple[str, str, str]] = set()

    group: tuple[int, date] | None = None  # kopje met alleen een datum, boven een groep uitjes

    for i, block in enumerate(blocks):
        if block.tag not in _HEADING_TAGS:
            continue
        rank = _HEADING_TAGS_RANK[block.tag]
        if not _valid_title(block.text):
            heading_date = parse_dutch_date(block.text, today) if _date_only(block.text) else None
            if heading_date:
                group = (rank, heading_date)
            elif group and rank <= group[0]:
                group = None
            continue
        if i in subtitles:
            continue
        if group and rank <= group[0]:
            group = None

        card = cards.get(i)

        def usable(other: HtmlBlock) -> bool:
            # Nooit een blok dat de kop zelf omvat (een lijst of pagina met alle uitjes erin),
            # en nooit iets uit het kaartje van een ander uitje.
            if other.element in block.ancestors:
                return False
            return not any(c in other.ancestors for c in card_ids if c != card)

        end = _next_heading_index(blocks, i, max(2, context_blocks), subtitles)
        forward = [b for b in blocks[i + 1:end] if usable(b)]
        # Op een pagina met kaartjes mag de datum ook vóór de titel staan (of in de kop zelf),
        # maar alleen binnen hetzelfde kaartje: nooit de datum van een ander uitje lenen.
        backward = []
        if card is not None:
            for b in reversed(blocks[max(0, i - context_blocks * 2):i]):
                if card not in b.ancestors:
                    break
                backward.append(b)

        date_index: int | None = None
        event_date: date | None = None
        date_text = ""
        for offset, nearby in enumerate(forward):
            parsed = parse_dutch_date(nearby.text, today)
            if parsed:
                event_date = parsed
                date_index = offset
                date_text = nearby.text
                break
        if event_date is None:
            for nearby in backward:
                parsed = parse_dutch_date(nearby.text, today)
                if parsed:
                    event_date = parsed
                    date_text = nearby.text
                    break

        if event_date is None and group:
            # Uitjes onder een datumkopje ('zaterdag 17 oktober'): die datum geldt voor de hele groep.
            event_date = group[1]
        if event_date is None:
            continue

        time_text = parse_time_range(date_text)
        if not time_text:
            rest = forward[(date_index + 1 if date_index is not None else 0):] + backward
            for nearby in rest:
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
        if not event_url and card is not None:
            # Kaartje dat in zijn geheel een link is: <a href="..."><h3>Titel</h3>...</a>
            event_url = next((b.href for b in forward + backward if b.href), None)

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
