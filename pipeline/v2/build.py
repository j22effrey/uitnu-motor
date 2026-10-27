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
from urllib.parse import urlparse

from collector.discover_venues import is_excluded

from pipeline import area

from .classify import FESTIVAL, classify, normalize, not_an_outing, venue_key
from .dekking import auto_register, coverage, load_register, merge_registers
from .convert import TICKET_HOSTS, content_hash, load_first_party, merge_duplicates, merge_key, to_v2
from .gate import MAX_CARRIED_HOSTS, dropped_hosts, run_gate
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
    if event.get("grensUitje"):
        return area.in_area(event["venue"].get("lat"), event["venue"].get("lon"), margin_km=area.GRENS_KM)
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
ROUTINE_MIN_SPAN_DAYS = 21  # korter dan drie weken is een reeks, geen clubavond: als hij pas later begint
ROUTINE_LATER_DAYS = 14     # (Night of the DinoLights in december) of dag na dag is (een herfstvakantieweek).
                            # Een vaste inloop die nu al loopt (elk weekend) blijft een vaste activiteit,
                            # ook als de website maar twee weken vooruit kijkt.


_MONTH = r"(?:jan|feb|maa|mrt|apr|mei|jun|jul|aug|sep|okt|oct|nov|dec)[a-z]*"


def _routine_key(event: dict) -> tuple[str, str]:
    # Tijden en datums tellen niet mee: 'Jeu de boules van 14:00 tot 16:00 uur' en 'Dorpskamer 20 oktober'
    # zijn elke week hetzelfde.
    title = re.sub(rf"\b\d{{1,2}}[:.]\d{{2}}\b|\b\d{{1,2}} {_MONTH}\b|\b(?:uur|van|tot|t/m|vanaf|om)\b", " ",
                   normalize(event.get("title") or ""))
    hosts = [s.get("host") for s in event.get("sources") or [] if s.get("host")]
    return " ".join(title.split()), (hosts[0] if hosts else "")


def routines(events: list[dict], today: date | None = None) -> set[int]:
    """Posities van uitjes die een vaste activiteit zijn (zie ROUTINE_*)."""
    groups: dict[tuple[str, str], list[int]] = {}
    for index, event in enumerate(events):
        groups.setdefault(_routine_key(event), []).append(index)
    drop: set[int] = set()
    for (title, _), indexes in groups.items():
        days = sorted({date.fromisoformat(events[i]["occurrences"][0]["date"]) for i in indexes})
        if not title or len(days) < ROUTINE_MIN:
            continue
        # Een rondgang: dezelfde lezing van de bibliotheek in Nieuwe Pekela, Winschoten en Onstwedde (één website
        # voor alle vestigingen), elke plaats één keer. Komt een plaats vaker terug, dan is het een vaste activiteit.
        cities = [normalize((events[i].get("venue") or {}).get("city") or "") for i in indexes]
        if all(cities) and len(set(cities)) == len(cities):
            continue
        gaps = sorted((b - a).days for a, b in zip(days, days[1:]))
        if (days[-1] - days[0]).days < ROUTINE_MIN_SPAN_DAYS and (
                gaps[-1] == 1 or (today and (days[0] - today).days > ROUTINE_LATER_DAYS)):
            continue
        median = gaps[len(gaps) // 2]
        if median <= ROUTINE_MAX_GAP_DAYS:
            drop |= {i for i in indexes if events[i].get("kind") not in ROUTINE_KEEP_KINDS}
        elif median <= 35 and len(days) >= 5:
            # Elke maand dezelfde bijeenkomst zonder herkenbare soort (een soos, een praatmiddag).
            drop |= {i for i in indexes if events[i].get("kind") == "overig"}
    return drop


# De Duitse of Engelse versie van een Nederlandse agenda ('/de/agenda/'): hetzelfde uitje nog een keer.
LANGUAGE_PATH = re.compile(r"^/(?:de|en|fr|da|pl)(?:[-_][a-z]{2})?/", re.IGNORECASE)


def translations(events: list[dict]) -> set[int]:
    """Posities van vertaalde uitjes waarvan dezelfde website op hetzelfde moment ook de Nederlandse
    versie heeft ('Ausflug mit Robbenspotting' naast 'Zeehondenkijktocht')."""
    slots: dict[tuple, list[int]] = {}
    for index, event in enumerate(events):
        first = event["occurrences"][0]
        hosts = [s.get("host") for s in event.get("sources") or [] if s.get("host")]
        slots.setdefault((hosts[0] if hosts else "", first.get("date"), first.get("startTime")), []).append(index)
    drop: set[int] = set()
    for indexes in slots.values():
        foreign = {i for i in indexes if LANGUAGE_PATH.match(urlparse(events[i].get("url") or "").path)}
        if foreign and len(foreign) < len(indexes):
            drop |= foreign
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
        # Wat de pagina zegt telt, behalve dat een filmvertoning een film blijft (een theater noemt ook de films
        # van zijn filmclub een 'voorstelling').
        if facts.get("type") and event.get("schemaType") != "ScreeningEvent":
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
    routine = routines(events, today)
    events = [e for i, e in enumerate(events) if i not in routine]
    translated = translations(events)
    events = [e for i, e in enumerate(events) if i not in translated]

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
    # Kaartverkoopsites tellen niet meer als bron (convert.TICKET_HOSTS): ook die mogen verdwijnen.
    gone = (retired or set()) | {h for h in previous_hosts if is_excluded(f"https://{h}/") or TICKET_HOSTS.search(h)}
    # Wat elke website aanleverde vóór de filters: een bron die levert, is niet kapot.
    delivered = Counter(h for e in converted + excluded + too_far
                        for h in {s.get("host") for s in e.get("sources") or [] if s.get("host")})
    in_area_previous = [e for e in previous if in_area(e)] if previous else previous
    # Een enkele bron die ineens leeg is: zijn uitjes van de vorige keer blijven staan (zie gate.MAX_CARRIED_HOSTS).
    carried: dict[str, int] = {}
    dropped = dropped_hosts(events, in_area_previous, today.isoformat(), retired_hosts=gone, delivered=delivered)
    if dropped and len(dropped) <= MAX_CARRIED_HOSTS:
        have = {e["id"] for e in events}
        # Niet dubbel: hetzelfde uitje kan nu via een andere website binnenkomen (andere id), en een adres
        # (slug) mag maar één keer voorkomen.
        slugs = {e.get("slug") for e in events}
        keys = {merge_key(e) for e in events}
        for old in in_area_previous:
            hosts_of = {s.get("host") for s in old.get("sources") or []}
            host = next((h for h in dropped if h in hosts_of), None)
            running = any((o.get("endDate") or o.get("date") or "") >= today.isoformat() for o in old.get("occurrences") or [])
            if (host and running and old["id"] not in have and old.get("slug") not in slugs
                    and merge_key(old) not in keys):
                events.append(old)
                have.add(old["id"])
                slugs.add(old.get("slug"))
                keys.add(merge_key(old))
                carried[host] = carried.get(host, 0) + 1
        delivered = delivered + Counter({h: n for h, n in carried.items()})
        events.sort(key=lambda e: (e["occurrences"][0]["date"], e["occurrences"][0].get("startTime") or "", e["title"]))
    gate = run_gate(events, in_area_previous, today.isoformat(), retired_hosts=gone, delivered=delivered)

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
        # Bronnen die ineens leeg waren: hun uitjes van de vorige keer bleven staan (nakijken in het onderhoud).
        "bewaardVanVorigeKeer": carried,
        "inputRecords": len(raw),
        "outsideArea": len(outside),
        "geenUitje": len(skipped),
        "vasteActiviteit": len(routine),
        "vertaling": len(translated),
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
        # Staat alles erin wat er zeker hoort? (collector/dekking.json)
        "dekking": _coverage(events, today),
    }
    status["_twijfel"] = doubts
    return events, status


def _coverage(events: list[dict], today: date) -> dict:
    """De dekkingscontrole mag de fabriek nooit laten vastlopen: een fout komt in het verslag."""
    try:
        root = HERE.parent.parent
        manual = load_register(root / "collector" / "dekking.json")
        hosts = {h.lower().removeprefix("www.") for places in (manual.get("plaatsen") or {}).values() for p in places
                 for h in p.get("hosts") or []}
        sources = load_register(root / "collector" / "web_crawl_sources.json").get("sources") or []
        off = {urlparse(x.get("rootUrl") or "").netloc.lower().removeprefix("www.") for x in sources
               if isinstance(x, dict) and x.get("enabled") is False}
        found = auto_register(load_register(root / "data" / "source_candidates.json"), hosts, off)
        return coverage(events, merge_registers(manual, found), today)
    except Exception as exc:  # noqa: BLE001 - een kapotte lijst is geen reden om niet te publiceren
        return {"gecontroleerd": 0, "fout": f"{type(exc).__name__}: {exc}"}


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
    gaps = status.get("dekking") or {}
    if gaps.get("gecontroleerd"):
        print(f"Dekking: {gaps['goed']} van {gaps['gecontroleerd']} plekken goed, {gaps.get('ontbreektTotaal', 0)} ontbreken, "
              f"{len(gaps['teWeinig'])} met te weinig uitjes.")
        for row in (gaps["teWeinig"] + gaps["ontbreekt"])[:15]:
            print(f"  DEKKING {row['plaats']}: {row['naam']} heeft {row['gevonden']} (verwacht {row['verwacht']}, {row['periode']})")
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
