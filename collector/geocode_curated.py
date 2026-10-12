"""Plaatsen zonder coördinaten in de handmatige agenda (data/events.json) opzoeken bij PDOK.

Zo kan een uitje met alleen een plaatsnaam worden toegevoegd (bijvoorbeeld na een tip van de
eigenaar); de motor zet de kaartpin er zelf bij. Alleen een exacte PDOK-woonplaats telt.

Draaien:  python -m collector.geocode_curated --file data/events.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from collector.title_place_inference import ALLOWED_TYPES, _norm


def fill_coordinates(path: str | Path, geocode_fn: Callable | None = None, timeout: float = 8) -> list[str]:
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    rows = json.loads(raw)
    if geocode_fn is None:
        from collector.pdok_geocode import geocode as geocode_fn
    filled: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("city"):
            continue
        if row.get("lat") is not None and row.get("lon") is not None:
            continue
        want = _norm(row["city"])
        try:
            results = geocode_fn(row["city"], rows=6, timeout=timeout)
        except Exception:
            continue  # PDOK even onbereikbaar: volgende ronde opnieuw
        for result in results:
            if (result.type or "").casefold() not in ALLOWED_TYPES:
                continue
            if _norm((result.label or "").split(",", 1)[0]) != want:
                continue
            row["lat"], row["lon"] = round(result.lat, 5), round(result.lon, 5)
            row["placeFromGeocoder"] = result.label
            filled.append(row["city"])
            break
    if filled:
        end = "\n" if raw.endswith("\n") else ""  # opmaak van het bestand gelijk houden
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + end, encoding="utf-8")
    return filled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UITNU: plaatsen zonder kaartpin opzoeken")
    parser.add_argument("--file", default="data/events.json")
    args = parser.parse_args(argv)
    filled = fill_coordinates(args.file)
    print(f"Kaartpin gezet bij {len(filled)} uitje(s){': ' + ', '.join(filled) if filled else ''}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
