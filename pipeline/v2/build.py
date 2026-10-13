"""De v2-fabriek in één commando.

    python -m pipeline.v2.build --data data --out data/v2

Stappen: eigen bronnen inlezen -> omzetten -> samenvoegen -> indelen -> keuren -> publiceren.
Exitcode 0 = gepubliceerd, 2 = keuring afgekeurd (vorige versie blijft staan).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from collector.discover_venues import is_excluded

from pipeline import area

from .classify import FESTIVAL, classify, normalize, not_an_outing, venue_key
from .convert import content_hash, load_first_party, merge_duplicates, to_v2
from .gate import run_gate
from .kinds import KINDS, TAGS
from .photos import attach_photos, host_of, list_pages, page_facts_for

HERE = Path(__file__).parent

# Werkgebied: Noord-Nederland (Groningen, Fryslân en Drenthe, plus een smalle rand over de grens).
# Instellen in pipeline/area.py (AREA_PROVINCES); landelijk is daar een langer lijstje provincies.
# Bezoekers kiezen op de site hun eigen straal.
AREA_CENTER = area.center()
AREA_RADIUS_KM = round(area.radius_km())   # cirkel om het hele gebied (voor zoekdiensten)
distance_km = area.distance_km


def in_area(event: dict) -> bool:
    return area.in_area(event["venue"].get("lat"), event["venue"].get("lon"))


def _read_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def source_kinds(path: Path) -> dict[str, str]:
    """Website -> soort uitje dat daar meestal is (veld kindHint in de bronnenlijst). Ook per zaal:
    uitjes van een theater met kaartjes op een andere website horen er toch bij."""
    payload = _read_json(path, {})
    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    kinds = {host_of(s.get("rootUrl")): s["kindHint"] for s in sources
             if isinstance(s, dict) and s.get("kindHint") and host_of(s.get("rootUrl"))}
    for s in sources:
        place = s.get("defaultPlace") if isinstance(s, dict) else None
        if s.get("kindHint") and isinstance(place, dict) and place.get("venue") and place.get("venue") != "naamloze plek":
            kinds[venue_key(place["venue"], place.get("city"))] = s["kindHint"]
    return kinds


def retired_hosts(path: Path) -> set[str]:
    """Websites die bewust uit staan in de bronnenlijst (enabled: false): hun uitjes mogen verdwijnen
    zonder dat de keuring denkt dat er iets kapot is."""
    payload = _read_json(path, {})
    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    return {host_of(s.get("rootUrl")) for s in sources
            if isinstance(s, dict) and s.get("enabled") is False and host_of(s.get("rootUrl"))}


def source_names(path: Path) -> dict[str, str]:
    """Website -> naam van de bron, voor de fotovermelding ('Foto: Neushoorn')."""
    payload = _read_json(path, {})
    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    return {host_of(s.get("rootUrl")): s["name"] for s in sources
            if isinstance(s, dict) and s.get("name") and host_of(s.get("rootUrl"))}


# Een uitje dat elke week (of vaker) terugkomt bij dezelfde organisator, zoals klaverjassen, gym,
# soos of jeu de boules, is een vaste activiteit van een club of dorpshuis en geen uitje voor de
# agenda. Voorstellingen, concerten, films, markten, tentoonstellingen en natuuruitjes blijven staan,
# ook als ze vaak terugkomen.
HORIZON_DAYS = 550          # uitjes verder vooruit: niet publiceren (zie build)
ROUTINE_KEEP_KINDS = {"theater", "muziek", "film", "festival", "markt", "kunst", "natuur"}
ROUTINE_MIN = 4             # minstens zo vaak in de agenda
ROUTINE_MAX_GAP_DAYS = 14   # en gemiddeld (mediaan) hoogstens zoveel dagen ertussen


def _routine_key(event: dict) -> tuple[str, str]:
    # Tijden tellen niet mee: 'Jeu de boules van 14:00 tot 16:00 uur' is elke week hetzelfde.
    title = re.sub(r"\b\d{1,2}[:.]\d{2}\b|\b(?:uur|van|tot|t/m|vanaf|om)\b", " ", normalize(event.get("title") or ""))
    hosts = [s.get("host") for s in event.get("sources") or [] if s.get("host")]
    return " ".join(title.split()), (hosts[0] if hosts else "")


def routines(events: list[dict]) -> set[int]:
    """Posities van uitjes die een vaste activiteit zijn (zie ROUTINE_*)."""
    groups: dict[tuple[str, str], list[int]] = {}
    for index, event in enumerate(events):
        groups.setdefault(_routine_key(event), []).append(index)
    drop: set[int] = set()
    for (title, _), indexes in groups.items():
        days = sorted({date.fromisoformat(events[i]["occurrences"][0]["date"]) for i in indexes})
        if not title or len(days) < ROUTINE_MIN:
            continue
        gaps = sorted((b - a).days for a, b in zip(days, days[1:]))
        median = gaps[len(gaps) // 2]
        if median <= ROUTINE_MAX_GAP_DAYS:
            drop |= {i for i in indexes if events[i].get("kind") not in ROUTINE_KEEP_KINDS}
        elif median <= 35 and len(days) >= 5:
            # Elke maand dezelfde bijeenkomst zonder herkenbare soort (een soos, een praatmiddag).
            drop |= {i for i in indexes if events[i].get("kind") == "overig"}
    return drop


def convert_all(raw: list[dict], today: date) -> tuple[list[dict], list[str]]:
    """Alle uitjes omzetten. Eén kapot uitje (rare gegevens van een nieuwe bron) mag de hele ronde niet
    laten vastlopen: dat uitje valt weg en komt in het verslag."""
    converted, broken = [], []
    for record in raw:
        try:
            event = to_v2(record, today)
        except Exception as error:
            broken.append(f"{str(record.get('title'))[:60]} ({record.get('sourceUrl')}): {type(error).__name__}")
            continue
        if event:
            converted.append(event)
    return converted, broken


def build(data_dir: Path, out_dir: Path, today: date, overrides: dict[str, str] | None = None,
          photo_cache: dict | None = None, names: dict[str, str] | None = None,
          venue_kinds: dict[str, str] | None = None, retired: set[str] | None = None) -> tuple[list[dict], dict]:
    raw = load_first_party(data_dir)
    converted, broken = convert_all(raw, today)
    # Vaste regel 1: nooit uitjes van een website op de uitsluitlijst (ook niet van een oude bron).
    excluded = [e for e in converted if any(is_excluded(u or "") for u in [e.get("url")] + [s.get("url") for s in e.get("sources") or []])]
    converted = [e for e in converted if e not in excluded]
    # Verder dan anderhalf jaar vooruit is bijna altijd een leesfout (een verkeerd jaar).
    horizon = (today + timedelta(days=HORIZON_DAYS)).isoformat()
    too_far = [e for e in converted if (e.get("occurrences") or [{}])[0].get("date", "") > horizon]
    converted = [e for e in converted if e not in too_far]
    outside = [e for e in converted if not in_area(e)]
    skipped = [e for e in converted if in_area(e) and not_an_outing(e)]
    events = merge_duplicates([e for e in converted if in_area(e) and not not_an_outing(e)])

    if photo_cache is None:
        photo_cache = _read_json(data_dir / "photos.json", {})
    lists = list_pages(events)

    before = len(events)
    for event in events:
        facts = page_facts_for(event, photo_cache, lists)
        if facts.get("type"):
            event["schemaType"] = facts["type"]
        if facts.get("hints"):
            event["pageHints"] = facts["hints"]
        verdict = classify(event, overrides, venue_kinds)
        event["kind"] = verdict["kind"]
        event["kindLabel"] = KINDS[verdict["kind"]]
        event["tags"] = verdict["tags"]
        event["classification"] = {k: verdict[k] for k in ("method", "reason", "confidence", "nakijken") if k in verdict}
        event.pop("description", None)
        for helper in ("legacyCategory", "legacyDiscipline", "schemaType", "pageHints"):
            event.pop(helper, None)
        event["hash"] = content_hash(event)
    if len(events) != before:
        raise RuntimeError("indelen mag nooit evenementen weglaten")
    # Vaste activiteiten (elke week klaverjassen, gym of soos) zijn geen uitjes voor de agenda.
    routine = routines(events)
    events = [e for i, e in enumerate(events) if i not in routine]

    # Unieke slugs, voor als twee titels toevallig hetzelfde worden afgekapt
    seen: Counter = Counter()
    for event in events:
        seen[event["slug"]] += 1
        if seen[event["slug"]] > 1:
            event["slug"] = f"{event['slug']}-{seen[event['slug']]}"

    events.sort(key=lambda e: (e["occurrences"][0]["date"], e["occurrences"][0].get("startTime") or "", e["title"]))

    # Foto's: organisator, anders Wikimedia Commons; zonder foto toont de site een tekstkaart.
    photo_counts = attach_photos(events, photo_cache, names)
    doubts = doubtful(events)

    previous = _read_json(out_dir / "events.json", None)
    # Uitjes buiten het werkgebied tellen niet mee in de vergelijking (na een kleiner werkgebied is
    # zo'n bron niet 'ineens leeg').
    # Bewust uitgezet: uit in de bronnenlijst, of een website op de uitsluitlijst.
    previous_hosts = {s.get("host") for e in previous or [] for s in e.get("sources") or [] if s.get("host")}
    gone = (retired or set()) | {h for h in previous_hosts if is_excluded(f"https://{h}/")}
    gate = run_gate(events, [e for e in previous if in_area(e)] if previous else previous, today.isoformat(),
                    retired_hosts=gone)

    prev_by_id = {e["id"]: e for e in previous or []}
    new_ids = {e["id"] for e in events}
    changes = {
        "new": sorted(e["id"] for e in events if e["id"] not in prev_by_id),
        "changed": sorted(e["id"] for e in events if e["id"] in prev_by_id and prev_by_id[e["id"]].get("hash") != e["hash"]),
        "removed": sorted(i for i in prev_by_id if i not in new_ids),
    }
    hosts: Counter = Counter(s["host"] for e in events for s in e["sources"] if s.get("host"))
    status = {
        "version": 2,
        "refreshedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "total": len(events),
        "inputRecords": len(raw),
        "outsideArea": len(outside),
        "geenUitje": len(skipped),
        "vasteActiviteit": len(routine),
        "teVerVooruit": len(too_far),
        "uitgeslotenBron": len(excluded),
        "onleesbaar": broken[:20],
        "area": area.describe(),
        "byKind": dict(Counter(e["kind"] for e in events).most_common()),
        "byCity": dict(Counter(e["venue"]["city"] for e in events).most_common()),
        "bySourceHost": dict(hosts.most_common()),
        "photos": photo_counts,
        "twijfel": len(doubts),
        "kinds": KINDS,
        "tags": TAGS,
        "changes": {k: len(v) for k, v in changes.items()},
        "gate": gate,
    }
    status["_twijfel"] = doubts
    return events, status


DOUBT_METHODS = {"geen", "bronhint", "locatie"}


def doubtful(events: list[dict]) -> list[dict]:
    """Uitjes waarvan de soort nagekeken moet worden (vaste regel 3: twijfelgevallen eerst uitzoeken)."""
    out = []
    for event in events:
        how = event.get("classification") or {}
        why = []
        if how.get("method") in DOUBT_METHODS:
            why.append("soort niet uit de titel en niet van de organisator zelf")
            if FESTIVAL.search(normalize(event.get("title") or "")):
                why.append("noemt zich festival, maar zonder bewijs van meerdere podia en artiesten")
        if how.get("nakijken"):
            why.append("ingedeeld met een vuistregel op naam; nog nakijken of het klopt")
        if event.get("kind") == "festival" and how.get("method") != "correctie":
            why.append("festival op grond van de tekst: controleren en zo nodig in het festivalregister zetten")
        if why:
            out.append({"id": event["id"], "title": event["title"], "kind": event["kind"],
                        "reason": how.get("reason"), "url": event.get("url"), "waarom": why})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UITNU v2-fabriek")
    parser.add_argument("--data", default="data", help="map met de eigen-bronbestanden")
    parser.add_argument("--out", default="data/v2", help="map voor events.json en status.json")
    parser.add_argument("--today", help="datum JJJJ-MM-DD (standaard: vandaag)")
    parser.add_argument("--force", action="store_true", help="publiceer ook als de keuring afkeurt")
    parser.add_argument("--sources", default="collector/web_crawl_sources.json",
                        help="bronnenlijst, voor de naam bij een foto van de organisator")
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else date.today()
    out_dir = Path(args.out)
    overrides = _read_json(HERE / "overrides.json", {})
    events, status = build(Path(args.data), out_dir, today, overrides, names=source_names(Path(args.sources)),
                           venue_kinds=source_kinds(Path(args.sources)), retired=retired_hosts(Path(args.sources)))

    doubts = status.pop("_twijfel", [])
    _write_json(out_dir / "twijfel.json", doubts)
    if status["gate"]["passed"] or args.force:
        _write_json(out_dir / "events.json", events)
        _write_json(out_dir / "status.json", status)
        print(f"Gepubliceerd: {status['total']} evenementen. Keuring: {'goed' if status['gate']['passed'] else 'GEFORCEERD'}.")
        return 0

    _write_json(out_dir / "events.rejected.json", events)
    for check in status["gate"]["checks"]:
        if not check["passed"]:
            print(f"KEURING AFGEKEURD - {check['name']}: {check['detail']}", file=sys.stderr)
    print("Niet gepubliceerd; de vorige versie blijft staan.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
