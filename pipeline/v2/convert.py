"""Zet de bestaande eigen-bronbestanden om naar de v2-vorm.

Invoer: data/events.json, data/confirmed_events.json, data/auto_events.json en
data/official_gap_events.json. Dat zijn evenementen van organisatoren, locaties en
de overheid. De VisitGroningen-kopie (public_groningen_events.json) wordt hier
bewust NIET gelezen.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from collector.source_candidates import canonical_url

FIRST_PARTY_FILES = (
    "events.json",
    "confirmed_events.json",
    "auto_events.json",
    "official_gap_events.json",
)

# Alleen deze statussen mogen publiek. Een aanvraag of kalendermelding is nog geen evenement.
PUBLISHABLE = {
    "organizer_confirmed": "bevestigd door de organisator",
    "structured_confirmed": "bevestigd door de organisator",
    "permit_granted": "vergund door de gemeente",
}

SOURCE_TYPES = {
    "organizer": "organisator",
    "event_official": "organisator",
    "municipality": "gemeente",
    "official": "overheid",
}

TIME = re.compile(r"(\d{1,2})[:.](\d{2})")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:80].strip("-") or "evenement"


def parse_time_range(value: str | None) -> tuple[str | None, str | None]:
    """'17:00 – 00:00' -> ('17:00', '00:00'); onbekend -> (None, None)."""
    found = TIME.findall(value or "")
    times = [f"{int(h):02d}:{m}" for h, m in found if int(h) < 24 and int(m) < 60]
    # Om 00:00 beginnen is bijna altijd 'tijd onbekend' (anders staat er 's nachts al 'Nu bezig').
    if not times or times[0] == "00:00":
        return None, None
    return times[0], (times[1] if len(times) > 1 else None)


def _web_link(value) -> str | None:
    """Een link zoals de organisator hem gaf, of None als het geen echt webadres is."""
    link = str(value or "").strip()
    return link if canonical_url(link) else None


def _host(url: str | None) -> str | None:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else None


def load_first_party(data_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for name in FIRST_PARTY_FILES:
        path = data_dir / name
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            row = dict(row)
            row["_file"] = name
            rows.append(row)
    return rows


_DAYS = r"(?:maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)"
_MONTHS = r"(?:januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)"
# '7 februari 2027 om 14.30 uur – Trio X' of 'Zondag 15 november 2026 – 14.30 uur – Y': de datum
# staat al in de agenda, dus die gaat van de titel af.
DATE_PREFIX = re.compile(
    rf"^\s*(?:{_DAYS}\s+)?\d{{1,2}}\s+{_MONTHS}(?:\s+\d{{4}})?"
    rf"(?:\s*(?:[-–—]|om)\s*\d{{1,2}}[.:]\d{{2}}(?:\s*uur)?)?\s*[-–—:]\s+", re.IGNORECASE)


# Een losse aanduiding achter de naam ('Durf moedig te zijn Start'): die hoort niet bij de naam.
TRAILING_LABEL = re.compile(r"\s+(?:start|datum|aanvang)\s*:?\s*$", re.IGNORECASE)
# Een tijd voor de naam ('16:00 Kerstmarkt'): de tijd staat al bij het uitje.
LEADING_TIME = re.compile(r"^\d{1,2}[:.]\d{2}(?:\s*(?:-|–|—|tot|t/m)\s*\d{1,2}[:.]\d{2})?(?:\s*uur)?\s*[-–—:]?\s+"
                          r"(?=[^\d\s])(?!(?:tot|t/m|[-–—])\s*\d)", re.IGNORECASE)
# Een postcode voor de plaatsnaam ('9341 BL Veenhuizen'): alleen de plaats telt.
POSTCODE_PREFIX = re.compile(r"^\d{4}\s?[A-Za-z]{2}\s+")
# Tekst voor schermlezers achter de naam ('Vaiana (opent bij de bron)'): hoort niet bij de naam.
LINK_NOTE = re.compile(r"\s*\((?:opent (?:bij de bron|in (?:een )?nieuw (?:venster|tabblad))|opens in (?:a )?new (?:window|tab)"
                       r"|externe link|external link)\)\s*", re.IGNORECASE)


def _undouble(title: str) -> str:
    """Een naam die er twee keer staat ('Taalcafé Taalcafé', of afgekapt: 'Kinderboekenweek: Spot aan! -
    met Mark in de bieb! Kinderboekenweek: Spot aan! - m'): één keer is genoeg."""
    for index, char in enumerate(title):
        if char != " ":
            continue
        first, second = title[:index].casefold(), title[index + 1:].casefold()
        twice = len(first) >= 7 and first == second
        cut_off = len(second) >= 12 and len(first) > len(second) and first.startswith(second)
        if twice or cut_off:
            return title[:index]
    return title


def clean_title(value: str | None) -> str:
    title = _undouble(LINK_NOTE.sub(" ", re.sub(r"\s+", " ", value or "")).strip())
    rest = DATE_PREFIX.sub("", title, count=1)
    rest = rest if len(rest) >= 3 else title
    untimed = LEADING_TIME.sub("", rest, count=1)
    rest = untimed if len(untimed) >= 3 else rest
    bare = TRAILING_LABEL.sub("", rest)
    return bare if len(bare.split()) >= 2 else rest


def to_v2(raw: dict, today: date) -> dict | None:
    """Een v2-evenement, of None als het (nog) niet publiek mag of al voorbij is."""
    status = raw.get("verificationStatus")
    if status not in PUBLISHABLE:
        return None
    if raw.get("publicAudience") is False:
        return None
    start = raw.get("startDate")
    if not start:
        return None
    end = raw.get("endDate") or start
    if end < start:
        end = start
    if end < today.isoformat():
        return None
    city = POSTCODE_PREFIX.sub("", (raw.get("city") or "").strip())
    # Alleen echte webadressen (kapotte HTML kan tekst of een e-mailadres in een link zetten), zonder
    # onzichtbare spaties eromheen: de site leest elke link na.
    links = {key: _web_link(raw.get(key)) for key in ("eventUrl", "organizerUrl", "sourceUrl", "discoveryUrl")}
    url = links["eventUrl"] or links["organizerUrl"] or links["sourceUrl"]
    if not city or not url:
        return None

    start_time, end_time = parse_time_range(raw.get("time"))
    occurrence = {"date": start, "endDate": end if end != start else None,
                  "startTime": start_time, "endTime": end_time}

    sources = []
    seen = set()
    for kind, link in (
        (SOURCE_TYPES.get(raw.get("sourceType") or "", "organisator"), links["sourceUrl"]),
        ("organisator", links["eventUrl"]),
        ("organisator", links["organizerUrl"]),
        ("vergunning", links["discoveryUrl"] if "officielebekendmakingen" in (links["discoveryUrl"] or "") else None),
    ):
        if link and link not in seen:
            seen.add(link)
            sources.append({"type": kind, "url": link, "host": _host(link),
                            "seenAt": raw.get("lastSourceAudit")})

    title = clean_title(raw.get("title"))
    return {
        "id": raw.get("id") or slugify(f"{title}-{city}-{start}"),
        "slug": slugify(f"{title}-{city}-{start}"),
        "title": title,
        "occurrences": [occurrence],
        "venue": {
            "name": (raw.get("location") or "").strip() or None,
            "city": city,
            "lat": raw.get("lat"),
            "lon": raw.get("lon"),
        },
        "price": (raw.get("price") or "").strip() or None,
        "url": url,
        "status": PUBLISHABLE[status],
        "sources": sources,
        # Alleen gebruikt om in te delen; de tekst zelf wordt niet gepubliceerd.
        "description": raw.get("description") or "",
        "legacyCategory": raw.get("category"),
        "legacyDiscipline": raw.get("cultureDiscipline"),
        "schemaType": raw.get("schemaType"),
    }


def merge_key(event: dict) -> tuple[str, str, str]:
    title = slugify(event["title"])
    return (title, event["occurrences"][0]["date"], slugify(event["venue"]["city"]))


def _merge_exact(events: list[dict]) -> list[dict]:
    """Hetzelfde evenement uit meerdere bestanden wordt één record met alle bronnen."""
    merged: dict[tuple[str, str, str], dict] = {}
    for event in events:
        key = merge_key(event)
        if key not in merged:
            merged[key] = event
            continue
        keep = merged[key]
        known = {s["url"] for s in keep["sources"]}
        keep["sources"] += [s for s in event["sources"] if s["url"] not in known]
        for field in ("price",):
            if not keep.get(field) and event.get(field):
                keep[field] = event[field]
        occ, other = keep["occurrences"][0], event["occurrences"][0]
        for field in ("startTime", "endTime", "endDate"):
            if not occ.get(field) and other.get(field):
                occ[field] = other[field]
    return list(merged.values())


def content_hash(event: dict) -> str:
    """Vingerafdruk om nieuw/gewijzigd/verdwenen te bepalen."""
    stable = {k: event.get(k) for k in ("title", "occurrences", "venue", "price", "url", "kind", "tags")}
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


_STOPWORDS = {"de", "het", "een", "en", "van", "in", "op", "te", "bij", "aan", "voor", "met", "the", "of", "and"}


def _title_words(title: str, city: str) -> set[str]:
    city_words = set(slugify(city or "").split("-"))
    return {w for w in slugify(title).split("-")
            if len(w) > 2 and not w.isdigit() and w not in _STOPWORDS and w not in city_words}


def _venue_key(event: dict) -> str | None:
    """Zaal en plaats samen. Zonder zaalnaam is er geen zaal om op samen te voegen
    (slugify('') geeft 'evenement', en dan zouden alle uitjes zonder zaal één plek lijken)."""
    raw_name = (event["venue"].get("name") or "").strip()
    if not raw_name:
        return None
    name = slugify(raw_name)
    city = slugify(event["venue"].get("city") or "")
    if name == city or name.startswith("diverse") or name.startswith("centrum"):
        return None
    return f"{name}|{city}"


def _same_slot(a: dict, b: dict) -> bool:
    oa, ob = a["occurrences"][0], b["occurrences"][0]
    if oa["date"] != ob["date"] or (oa.get("endDate") or oa["date"]) != (ob.get("endDate") or ob["date"]):
        return False
    return not (oa.get("startTime") and ob.get("startTime") and oa["startTime"] != ob["startTime"])


def merge_same_venue(events: list[dict]) -> list[dict]:
    """Twee namen voor hetzelfde uitje: zelfde plek, zelfde dagen en tijd, en een gedeeld woord in de titel."""
    result: list[dict] = []
    for event in events:
        key = _venue_key(event)
        twin = None
        if key:
            words = _title_words(event["title"], event["venue"].get("city"))
            for other in result:
                if (_venue_key(other) == key and _same_slot(other, event)
                        and words & _title_words(other["title"], other["venue"].get("city"))):
                    twin = other
                    break
        if twin is None:
            result.append(event)
            continue
        known = {s["url"] for s in twin["sources"]}
        twin["sources"] += [s for s in event["sources"] if s["url"] not in known]
        occ, extra = twin["occurrences"][0], event["occurrences"][0]
        for field in ("startTime", "endTime"):
            if not occ.get(field) and extra.get(field):
                occ[field] = extra[field]
        for field in ("url", "price"):
            if not twin.get(field) and event.get(field):
                twin[field] = event[field]
        twin["tags"] = sorted(set(twin.get("tags") or []) | set(event.get("tags") or []))
    return result


def merge_duplicates(events: list[dict]) -> list[dict]:
    """Hetzelfde evenement uit meerdere bestanden wordt één record met alle bronnen."""
    return merge_same_venue(_merge_exact(events))
