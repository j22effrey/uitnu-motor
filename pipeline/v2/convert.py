"""Zet de bestaande eigen-bronbestanden om naar de v2-vorm.

Invoer: data/events.json, data/confirmed_events.json, data/auto_events.json en
data/official_gap_events.json. Dat zijn evenementen van organisatoren, locaties en
de overheid. De VisitGroningen-kopie (public_groningen_events.json) wordt hier
bewust NIET gelezen.
"""
from __future__ import annotations

import hashlib
import json
from html import unescape
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


# Kaartverkoopsites: geen bron en geen link voor het uitje (vaste regel 1: de organisator is de bron;
# Stager verbiedt bovendien alle bots). Dan wordt de agenda van de organisator de link.
TICKET_HOSTS = re.compile(r"(?:^|\.)(?:stager\.co|ticketmaster\.\w+|eventix\.io|shop\.eventix\.io|ticketmatic\.com"
                          r"|eventbrite\.\w+|tickettailor\.com|ticketkantoor\.nl|mijnetickets\.nl|shop\.weeztix\.com)$", re.I)


def _web_link(value) -> str | None:
    """Een link zoals de organisator hem gaf, of None als het geen echt webadres is (of een kaartverkoopsite)."""
    link = str(value or "").strip()
    if not canonical_url(link) or TICKET_HOSTS.search(_host(link) or ""):
        return None
    return link


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


# Praktische zaken als los deel van de naam ('LBE – Dido & Aeneas – Groningen – Martinikerk – 22 oktober 2026 –
# aanvang 19.30 uur – jongeren t/m 27 jaar – zaal open 30 minuten voor aanvang concert'): staan al bij het uitje.
_DATE = rf"\d{{1,2}}\s+{_MONTHS}(?:\s+\d{{4}})?"
PRACTICAL_PART = re.compile(
    rf"^(?:(?:{_DAYS}\s+)?{_DATE}|aanvang\b.*|zaal open\b.*|deuren open\b.*|(?:kinderen en )?jongeren t/m \d+ jaar"
    rf"|(?:eerste rang|tweede rang|reguliere?|losse|vip)\s+tickets?)$",
    re.IGNORECASE)
TITLE_PARTS = re.compile(r"\s*[–—]\s*|\s+-\s+|\s*\|\s*")
# Een datum of tijd aan het eind van een deel: 'Scherven van de Wereld wo 11 nov' (of 'vr 20 – zo 22 nov'), 'Toneelvereniging ODI, zaterdag
# 20.15u', 'Nacht van de Nacht van 19.30 – ca. 21.00 uur. Verzamelen bij de kerk', 'WO II 7 november 2026 t/m 17 mei 2027'.
TRAILING_WHEN = re.compile(
    rf"(?:(?:\s+(?:ma|di|wo|do|vr|za|zo)\s+\d{{1,2}}\s*[–-])?\s+(?:ma|di|wo|do|vr|za|zo)\s+\d{{1,2}}\s+(?:jan|feb|mrt|apr|mei|jun|jul|aug|sep|okt|nov|dec)"
    rf"|,\s*{_DAYS}\s+\d{{1,2}}[.:]\d{{2}}\s*u(?:ur)?"
    rf"|\s+(?:van\s+)?\d{{1,2}}[.:]\d{{2}}\s*[–-]\s*(?:ca\.\s*)?\d{{1,2}}[.:]\d{{2}}\s*uur\b.*"
    rf"|\s+{_DATE}\s+(?:t/m|tot en met|tot|[–-])\s+{_DATE})$", re.IGNORECASE)
# Een aanduiding voor de naam ('Activiteit Concert van NIHZ', 'Nu te zien: fotografe ...').
LEADING_LABEL = re.compile(r"^(?:activiteit:?|nu te zien:|scoor je tickets(?: voor)?:?)\s+(?=\S)", re.IGNORECASE)
# Een schreeuwende melding achter de naam ('Theeproeverij *WEGENS SUCCES VOLGEBOEKT*').
TRAILING_SHOUT = re.compile(r"\s*\*[^*a-z]{4,}\*\s*$")


def _tidy(title: str, city: str | None, venue: str | None) -> str:
    """Haalt de praktische zaken uit een lange naam: datum, aanvang, zaal open, leeftijd, en de plaats of het
    gebouw als los deel. Het eerste deel blijft altijd staan; een deel van de echte naam ook."""
    places = {slugify(place) for place in (city, venue) if place}
    places |= {slugify(part) for part in re.split(r"[,(/|]|\s+I\s+", venue or "") if part.strip()}
    unlabeled = LEADING_LABEL.sub("", title)
    if unlabeled != title:
        title = unlabeled[:1].upper() + unlabeled[1:]
    title = TRAILING_SHOUT.sub("", title)
    parts = TITLE_PARTS.split(title)
    if len(parts) > 1:
        drop = {index for index, part in enumerate(parts)
                if index and (PRACTICAL_PART.match(part) or slugify(part) in places
                              or f"-{slugify(part)}-" in f"-{slugify(venue or '')}-")}
        kept = [part for index, part in enumerate(parts) if index not in drop]
        # Blijft er één los woord over ('Muziek | De Oosterpoort'), dan is de hele naam nodig om uitjes uit elkaar
        # te houden.
        if drop and len(" ".join(kept).split()) >= 2:
            title = " – ".join(kept)
    shorter = TRAILING_WHEN.sub("", title)
    return _undouble(shorter if len(shorter.split()) >= 2 else title)


def clean_title(value: str | None, city: str | None = None, venue: str | None = None) -> str:
    # '&amp;' en '&#8211;' uit de HTML van de bron: tekens zoals de organisator ze bedoelt (twee keer, voor '&amp;amp;').
    entity = re.compile(r"&#?\w+;")  # alleen met puntkomma: 'Kunst&centrum' blijft heel
    text = entity.sub(lambda m: unescape(m.group()), entity.sub(lambda m: unescape(m.group()), value or ""))
    title = _undouble(LINK_NOTE.sub(" ", re.sub(r"\s+", " ", text)).strip())
    rest = DATE_PREFIX.sub("", title, count=1)
    rest = rest if len(rest) >= 3 else title
    untimed = LEADING_TIME.sub("", rest, count=1)
    rest = untimed if len(untimed) >= 3 else rest
    # Een tijd achter de naam ('BEEF 16:00 - 17:05', Jonge Harten): die staat al bij het uitje.
    timed = re.sub(r"\s+(?:[|I]\s+)?\d{1,2}[:.]\d{2}\s*[-–]\s*\d{1,2}[:.]\d{2}$", "", rest)
    rest = timed if len(timed) >= 3 else rest
    bare = TRAILING_LABEL.sub("", rest)
    return _tidy(bare if len(bare.split()) >= 2 else rest, city, venue)


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
    # Is de link van het uitje een e-mailadres, dan is de agenda waar het op staat de link.
    links = {key: _web_link(raw.get(key)) for key in ("eventUrl", "organizerUrl", "sourceUrl", "discoveryUrl", "sourceRoot")}
    url = links["eventUrl"] or links["organizerUrl"] or links["sourceUrl"] or links["sourceRoot"]
    if not city or not url:
        return None

    start_time, end_time = parse_time_range(raw.get("time"))
    occurrence = {"date": start, "endDate": end if end != start else None,
                  "startTime": start_time, "endTime": end_time}

    sources = []
    seen = set()
    for kind, link in (
        (SOURCE_TYPES.get(raw.get("sourceType") or "", "organisator"), links["sourceUrl"] or links["sourceRoot"]),
        ("organisator", links["eventUrl"]),
        ("organisator", links["organizerUrl"]),
        ("vergunning", links["discoveryUrl"] if "officielebekendmakingen" in (links["discoveryUrl"] or "") else None),
    ):
        if link and link not in seen:
            seen.add(link)
            sources.append({"type": kind, "url": link, "host": _host(link),
                            "seenAt": raw.get("lastSourceAudit")})

    title = clean_title(raw.get("title"), city, raw.get("location"))
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
        # Een groot evenement verder over de grens (grensregister, zoals de Gallimarkt in Leer): mag verder weg liggen.
        **({"grensUitje": True} if raw.get("grensUitje") else {}),
    }


def merge_key(event: dict) -> tuple[str, str, str]:
    title = slugify(event["title"])
    return (title, event["occurrences"][0]["date"], slugify(event["venue"]["city"]))


def _keep_screening(keep: dict, event: dict) -> None:
    """Noemt één van de bronnen het een filmvertoning, dan is het een film: een theater dat ook films draait
    zet ze in het theaterprogramma als 'voorstelling' (Theater De Winsinghhof Roden, de filmclub)."""
    if event.get("schemaType") == "ScreeningEvent" and keep.get("schemaType") != "ScreeningEvent":
        keep["schemaType"] = "ScreeningEvent"


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
        _keep_screening(keep, event)
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


_STOPWORDS = {"de", "het", "een", "en", "van", "in", "op", "te", "bij", "aan", "voor", "met", "the", "of", "and",
              "support", "live", "feat", "presenteert", "presents", "voorstelling", "concert", "lezing"}


def _title_words(title: str, city: str, venue: str = "") -> set[str]:
    # De plaats en de naam van de plek zelf zeggen niets over welk uitje het is ('Drents-Friese Wold').
    city_words = set(slugify(city or "").split("-")) | set(slugify(venue or "").split("-"))
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


def _same_city_time(a: dict, b: dict) -> bool:
    """Zelfde plaats, dagen en een bekende, gelijke begintijd."""
    oa, ob = a["occurrences"][0], b["occurrences"][0]
    city = slugify(a["venue"].get("city") or "")
    return (bool(a["venue"].get("city")) and city == slugify(b["venue"].get("city") or "") and _same_slot(a, b)
            and bool(oa.get("startTime")) and oa.get("startTime") == ob.get("startTime"))


def _vague_twin(a: dict, b: dict) -> bool:
    """De ene kant noemt alleen de plaats en geen tijd (de dorpsagenda: 'Voorstelling X' in Workum), de andere
    heeft een echte zaal (Kultuerhús Klameare): zelfde plaats en dagen."""
    def vague(e: dict) -> bool:
        return _venue_key(e) is None and not e["occurrences"][0].get("startTime")
    oa, ob = a["occurrences"][0], b["occurrences"][0]
    days = oa["date"] == ob["date"] and (oa.get("endDate") or oa["date"]) == (ob.get("endDate") or ob["date"])
    city = slugify(a["venue"].get("city") or "")
    return (days and bool(city) and city == slugify(b["venue"].get("city") or "")
            and (vague(a) != vague(b)) and bool(_venue_key(a) or _venue_key(b)))


def _same_name(a: set[str], b: set[str]) -> bool:
    """Twee namen voor hetzelfde uitje: de ene naam zit helemaal in de andere ('HAEVN' en 'HAEVN + support'),
    of ze delen minstens twee woorden. Eén gedeeld woord is te weinig in een zaal met meerdere zalen: in De
    Oosterpoort verdwenen zo concerten op dezelfde avond ('Noord-Nederlands Orkest', oktober 2026)."""
    shared = a & b
    return bool(shared) and (len(shared) >= 2 or shared in (a, b))


def merge_same_venue(events: list[dict]) -> list[dict]:
    """Twee namen voor hetzelfde uitje: zelfde plek, zelfde dagen en tijd, en een gedeeld woord in de titel."""
    result: list[dict] = []
    for event in events:
        key = _venue_key(event)
        twin = None
        words = _title_words(event["title"], event["venue"].get("city"), event["venue"].get("name"))
        if key:
            for other in result:
                if (_venue_key(other) == key and _same_slot(other, event)
                        and _same_name(words, _title_words(other["title"], other["venue"].get("city"), other["venue"].get("name")))):
                    twin = other
                    break
        if twin is None and words:
            # Hetzelfde uitje op twee websites (het dorp en het theater: 'Voorstelling Laurens de Groot – HUN' en
            # 'Laurens de Groot – HUN'), met een andere zaalnaam: zelfde plaats, dag en begintijd, en de ene naam
            # zit helemaal in de andere. Alleen met een echte zaal aan beide kanten (niet 'Centrum Delfzijl').
            for other in result:
                if _same_city_time(other, event) if (key and _venue_key(other)) else _vague_twin(other, event):
                    theirs = _title_words(other["title"], other["venue"].get("city"), other["venue"].get("name"))
                    if theirs and (words <= theirs or theirs <= words):
                        twin = other
                        break
        if twin is None:
            result.append(event)
            continue
        if _venue_key(twin) is None and _venue_key(event):
            # De zaal en de naam van de zaal zelf zijn preciezer dan die van de dorpsagenda.
            twin["venue"], twin["title"] = event["venue"], event["title"]
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
