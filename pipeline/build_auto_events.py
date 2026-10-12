"""Build the public auto-generated event feed from trusted staged sources.

Curated data/events.json remains authoritative. This module only emits additional
publishable events that are not already represented in the curated feed.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlparse

AUTO_STATUSES = {"organizer_confirmed", "permit_granted"}
MAX_AUTO_EVENT_DURATION_DAYS = 31

CATEGORY_LABELS = {
    "open_dag": "Open dag",
    "festival": "Festival",
    "markt": "Markt & braderie",
    "kermis": "Kermis",
    "expo": "Expo & beurs",
    "food": "Food & lokaal",
    "sport": "Sport",
    "familie": "Familie",
    "muziek": "Muziek",
    "feest": "Feest",
    "overig": "Evenement",
    "cultuur": "Podium & cultuur",
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(text[:19])
        except ValueError:
            return None


def _source_host(item: dict) -> str:
    urls = item.get("source_urls") or []
    if not isinstance(urls, list):
        urls = []
    for value in urls:
        try:
            host = (urlparse(str(value)).hostname or "").casefold()
        except ValueError:
            host = ""
        if host:
            return host.removeprefix("www.")
    return ""


# Wat de organisator zelf opgeeft als schema.org-soort -> (categorie, discipline).
# Alleen gebruikt als de titel zelf niets zegt.
SCHEMA_TYPES: dict[str, tuple[str, str | None]] = {
    "musicevent": ("muziek", None),
    "festival": ("festival", None),
    "foodevent": ("food", None),
    "sportsevent": ("sport", None),
    "exhibitionevent": ("expo", None),
    "visualartsevent": ("expo", None),
    "childrensevent": ("familie", None),
    "theaterevent": ("cultuur", "theater"),
    "comedyevent": ("cultuur", "cabaret"),
    "danceevent": ("cultuur", "dans"),
    "screeningevent": ("cultuur", "film"),
    "literaryevent": ("cultuur", "literatuur"),
}


def _classify(item: dict) -> tuple[str, str, str | None]:
    host = _source_host(item)
    title = _norm(item.get("title"))
    source_category = _norm(item.get("category"))
    schema = SCHEMA_TYPES.get(source_category.replace(" ", ""))
    hay = f"{title} {source_category}"

    if host.endswith("spotgroningen.nl"):
        discipline = "muziek"
        if any(x in hay for x in ("theater", "toneel", "musical")):
            discipline = "theater"
        elif any(x in hay for x in ("cabaret", "comedy", "stand up")):
            discipline = "cabaret"
        elif any(x in hay for x in ("dans", "ballet")):
            discipline = "dans"
        elif any(x in hay for x in ("opera", "klassiek", "orkest")):
            discipline = "klassiek_opera"
        elif any(x in hay for x in ("expo", "kunst", "tentoonstelling")):
            discipline = "kunst_expo"
        elif any(x in hay for x in ("film", "cinema")):
            discipline = "film"
        elif any(x in hay for x in ("literatuur", "boek", "lezing", "talk")):
            discipline = "literatuur"
        elif schema and schema[1]:
            discipline = schema[1]  # de organisator zegt zelf wat het is
        return "cultuur", "Podium & cultuur", discipline

    if host.endswith("kindermaand.nl"):
        return "familie", CATEGORY_LABELS["familie"], None
    if any(x in hay for x in ("open dag", "open huis")):
        key = "open_dag"
    elif "kermis" in hay:
        key = "kermis"
    elif any(x in hay for x in ("markt", "braderie", "fair", "jaarmarkt", "boekenmarkt")):
        key = "markt"
    elif any(x in hay for x in ("festival", "fest")):
        key = "festival"
    elif any(x in hay for x in ("beurs", "expo", "autosalon", "show")):
        key = "expo"
    elif any(x in hay for x in ("food", "culinair", "proeverij")):
        key = "food"
    elif any(x in hay for x in ("run", "marathon", "wedstrijd", "sport")):
        key = "sport"
    elif any(x in hay for x in ("kind", "familie", "circus")):
        key = "familie"
    elif any(x in hay for x in ("concert", "muziek", "band")):
        key = "muziek"
    elif any(x in hay for x in ("feest", "party")):
        key = "feest"
    elif schema:
        return schema[0], CATEGORY_LABELS[schema[0]], schema[1]
    else:
        key = "overig"
    return key, CATEGORY_LABELS[key], None


def _format_time(start: datetime | None, end: datetime | None) -> str:
    if not start:
        return "Zie organisator"
    if start.hour == 0 and start.minute == 0 and end and end.hour == 23 and end.minute >= 55:
        return "Zie organisator"
    if not end:
        return start.strftime("%H:%M") if (start.hour or start.minute) else "Zie organisator"
    if start.date() == end.date():
        return f"{start:%H:%M} – {end:%H:%M}"
    if end.date() == start.date() + timedelta(days=1) and end.time() < start.time():
        # One continuous overnight session, not an unspecified multi-day festival.
        return f"{start:%H:%M} – {end:%H:%M}"
    return "Diverse tijden"


def canonical_to_public(item: dict, *, audit_date: date) -> dict | None:
    start = _parse_datetime(item.get("start_at"))
    end = _parse_datetime(item.get("end_at"))
    if not start:
        return None
    if end and (end.date() < start.date() or (
        end.date() == start.date() and end.time() < start.time()
    )):
        # Do not publish a reversed time range as a valid public event.
        return None
    urls = [str(x) for x in (item.get("source_urls") or []) if x]
    if not urls:
        return None
    category, category_label, discipline = _classify(item)
    source_url = urls[0]
    record = {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or "").strip(),
        "category": category,
        "categoryLabel": category_label,
        "startDate": start.date().isoformat(),
        "endDate": end.date().isoformat() if end and end.date() != start.date() else None,
        "time": _format_time(start, end),
        "location": item.get("venue") or item.get("address") or item.get("city") or "Zie organisator",
        "city": item.get("city"),
        "lat": item.get("lat"),
        "lon": item.get("lon"),
        "price": item.get("price_text") or "Zie organisator",
        "sourceType": "event_official",
        "verificationStatus": str(item.get("verification_status") or "organizer_confirmed"),
        "sourceNote": "Automatisch bevestigd via een geactiveerde officiële organisator- of venuebron.",
        "sourceUrl": source_url,
        "eventUrl": source_url,
        "experienceGroup": "culture" if category == "cultuur" else "outing",
        "publicAudience": True,
        "lastSourceAudit": audit_date.isoformat(),
        "generatedBy": "active-source-pipeline",
    }
    if discipline:
        record["cultureDiscipline"] = discipline
    return record


def _start_time_key(value: object) -> str:
    """Return a known local showtime, not an unspecified/CMS timestamp."""
    match = re.match(r"^\s*([01]?\d|2[0-3]):([0-5]\d)(?!\d)", str(value or ""))
    return f"{int(match.group(1)):02}:{match.group(2)}" if match else ""


def _same_event(a: dict, b: dict) -> bool:
    if str(a.get("startDate") or "")[:10] != str(b.get("startDate") or "")[:10]:
        return False
    atime, btime = _start_time_key(a.get("time")), _start_time_key(b.get("time"))
    if atime and btime and atime != btime:
        return False
    ac, bc = _norm(a.get("city")), _norm(b.get("city"))
    if ac and bc and ac != bc:
        return False
    at, bt = _norm(a.get("title")), _norm(b.get("title"))
    if not at or not bt:
        return False
    if at == bt:
        return True
    if at in bt or bt in at:
        shorter = at if len(at) < len(bt) else bt
        if len(shorter) >= 10:
            return True
    return SequenceMatcher(None, at, bt).ratio() >= 0.90


def _valid_live_window(record: dict, today: date) -> bool:
    try:
        start = date.fromisoformat(str(record.get("startDate") or ""))
        end = date.fromisoformat(str(record.get("endDate") or record.get("startDate") or ""))
    except ValueError:
        return False
    if end < start:
        return False
    if (end - start).days > MAX_AUTO_EVENT_DURATION_DAYS:
        return False
    if end < today:
        return False
    return True


def _host(url: object) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def build_auto_events(curated: list[dict], staged: dict, *, today: date | None = None,
                      previous: list[dict] | None = None) -> list[dict]:
    """De automatische uitjes. previous = de vorige uitkomst: een bron die deze keer niet helemaal
    lukte (storing of tijd op), houdt zijn nog komende uitjes van de vorige keer."""
    today = today or date.today()
    canonical = staged.get("canonical_publishable", []) if isinstance(staged, dict) else []
    out: list[dict] = []
    for item in canonical:
        if not isinstance(item, dict):
            continue
        if item.get("verification_status") not in AUTO_STATUSES:
            continue
        record = canonical_to_public(item, audit_date=today)
        if not record or not _valid_live_window(record, today):
            continue
        if any(_same_event(record, existing) for existing in curated if isinstance(existing, dict)):
            continue
        if any(_same_event(record, existing) for existing in out):
            continue
        out.append(record)
    runs = staged.get("source_runs") if isinstance(staged, dict) else None
    unfinished = {_host(run.get("rootUrl")) for run in (runs or {}).values()
                  if isinstance(run, dict) and run.get("complete") is False and run.get("rootUrl")}
    unfinished.discard("")
    for record in previous or []:
        if not isinstance(record, dict) or _host(record.get("sourceUrl")) not in unfinished:
            continue
        if not _valid_live_window(record, today):
            continue
        if any(_same_event(record, existing) for existing in curated if isinstance(existing, dict)):
            continue
        if any(_same_event(record, existing) for existing in out):
            continue
        out.append(record)
    out.sort(key=lambda x: (x.get("startDate") or "9999-12-31", _norm(x.get("title"))))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build additional public events from trusted staged source output")
    parser.add_argument("--curated", default="data/events.json")
    parser.add_argument("--staged", default="active-source-staging.json")
    parser.add_argument("--output", default="data/auto_events.json")
    parser.add_argument("--today")
    args = parser.parse_args()
    curated = json.loads(Path(args.curated).read_text(encoding="utf-8"))
    staged = json.loads(Path(args.staged).read_text(encoding="utf-8"))
    today = date.fromisoformat(args.today) if args.today else date.today()
    try:
        previous = json.loads(Path(args.output).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = []
    output = build_auto_events(curated, staged, today=today, previous=previous if isinstance(previous, list) else [])
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"generated": len(output), "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
