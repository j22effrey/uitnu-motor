"""De v2-fabriek in één commando.

    python -m pipeline.v2.build --data data --out data/v2

Stappen: eigen bronnen inlezen -> omzetten -> samenvoegen -> indelen -> keuren -> publiceren.
Exitcode 0 = gepubliceerd, 2 = keuring afgekeurd (vorige versie blijft staan).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from .classify import classify
from .convert import content_hash, load_first_party, merge_duplicates, to_v2
from .gate import run_gate
from .kinds import KINDS, TAGS

HERE = Path(__file__).parent

# Werkgebied: Groningen en de rand van Drenthe en Friesland. Bezoekers kiezen hun eigen straal.
AREA_CENTER = (53.2194, 6.5665)  # Groningen-centrum
AREA_RADIUS_KM = 60


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def in_area(event: dict) -> bool:
    lat, lon = event["venue"].get("lat"), event["venue"].get("lon")
    if lat is None or lon is None:
        return True
    return distance_km(AREA_CENTER[0], AREA_CENTER[1], float(lat), float(lon)) <= AREA_RADIUS_KM


def _read_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build(data_dir: Path, out_dir: Path, today: date, overrides: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    raw = load_first_party(data_dir)
    converted = [e for e in (to_v2(r, today) for r in raw) if e]
    outside = [e for e in converted if not in_area(e)]
    events = merge_duplicates([e for e in converted if in_area(e)])

    before = len(events)
    for event in events:
        verdict = classify(event, overrides)
        event["kind"] = verdict["kind"]
        event["kindLabel"] = KINDS[verdict["kind"]]
        event["tags"] = verdict["tags"]
        event["classification"] = {k: verdict[k] for k in ("method", "reason", "confidence")}
        event.pop("description", None)
        event.pop("legacyCategory", None)
        event["hash"] = content_hash(event)
    if len(events) != before:
        raise RuntimeError("indelen mag nooit evenementen weglaten")

    # Unieke slugs, voor als twee titels toevallig hetzelfde worden afgekapt
    seen: Counter = Counter()
    for event in events:
        seen[event["slug"]] += 1
        if seen[event["slug"]] > 1:
            event["slug"] = f"{event['slug']}-{seen[event['slug']]}"

    events.sort(key=lambda e: (e["occurrences"][0]["date"], e["occurrences"][0].get("startTime") or "", e["title"]))

    previous = _read_json(out_dir / "events.json", None)
    gate = run_gate(events, previous, today.isoformat())

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
        "area": {"center": AREA_CENTER, "radiusKm": AREA_RADIUS_KM},
        "byKind": dict(Counter(e["kind"] for e in events).most_common()),
        "byCity": dict(Counter(e["venue"]["city"] for e in events).most_common()),
        "bySourceHost": dict(hosts.most_common()),
        "kinds": KINDS,
        "tags": TAGS,
        "changes": {k: len(v) for k, v in changes.items()},
        "gate": gate,
    }
    return events, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UITNU v2-fabriek")
    parser.add_argument("--data", default="data", help="map met de eigen-bronbestanden")
    parser.add_argument("--out", default="data/v2", help="map voor events.json en status.json")
    parser.add_argument("--today", help="datum JJJJ-MM-DD (standaard: vandaag)")
    parser.add_argument("--force", action="store_true", help="publiceer ook als de keuring afkeurt")
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else date.today()
    out_dir = Path(args.out)
    overrides = _read_json(HERE / "overrides.json", {})
    events, status = build(Path(args.data), out_dir, today, overrides)

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
