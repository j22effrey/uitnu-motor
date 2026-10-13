"""Het werkgebied van UITNU: een lijstje provincies, plus een smalle rand over de grens.

Nu: Noord-Nederland (Groningen, Fryslân en Drenthe). Landelijk wordt het later alleen een langer
lijstje in AREA_PROVINCES. De rand (MARGIN_KM) houdt uitjes vlak over de grens erin, zoals de
schouwburg in Steenwijk of de Kunsthalle in Emden.

De grenzen komen uit pipeline/provincies.json: de provinciegrenzen van het CBS (PDOK,
gebiedsindelingen 2025, gegeneraliseerd en vereenvoudigd tot ongeveer 200 meter).
"""
from __future__ import annotations

import json
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

AREA_PROVINCES = ("Groningen", "Fryslân", "Drenthe")
MARGIN_KM = 10
PROVINCES_PATH = Path(__file__).with_name("provincies.json")
AREA_LABEL = "Noord-Nederland"


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


@lru_cache(maxsize=None)
def _rings(provinces: tuple[str, ...] = AREA_PROVINCES) -> tuple[tuple[tuple[float, float], ...], ...]:
    data = json.loads(PROVINCES_PATH.read_text(encoding="utf-8"))["provincies"]
    return tuple(tuple((float(x), float(y)) for x, y in ring) for name in provinces for ring in data[name]["ringen"])


def _inside(lat: float, lon: float, rings) -> bool:
    """Even-oneven-regel over alle ringen (gaten in een provincie tellen dan vanzelf goed)."""
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def _near_edge(lat: float, lon: float, rings, km: float) -> bool:
    """Ligt het punt binnen 'km' van een grens? (Plat gerekend: op deze afstanden nauwkeurig genoeg.)"""
    k = cos(radians(lat)) * 111.32   # km per graad lengte hier
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            ax, ay, bx, by = (x1 - lon) * k, (y1 - lat) * 110.57, (x2 - lon) * k, (y2 - lat) * 110.57
            dx, dy = bx - ax, by - ay
            t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
            if (ax + t * dx) ** 2 + (ay + t * dy) ** 2 <= km * km:
                return True
    return False


def in_area(lat: float | None, lon: float | None, *, provinces: tuple[str, ...] = AREA_PROVINCES,
            margin_km: float = MARGIN_KM) -> bool:
    """Ligt dit punt in het werkgebied (of vlak over de grens)? Zonder plek: ja (niet weggooien)."""
    if lat is None or lon is None:
        return True
    lat, lon = float(lat), float(lon)
    rings = _rings(tuple(provinces))
    return _inside(lat, lon, rings) or (margin_km > 0 and _near_edge(lat, lon, rings, margin_km))


@lru_cache(maxsize=None)
def bounds(provinces: tuple[str, ...] = AREA_PROVINCES) -> tuple[float, float, float, float]:
    """(zuid, west, noord, oost) van het werkgebied, met de rand erbij."""
    points = [p for ring in _rings(tuple(provinces)) for p in ring]
    south, north = min(y for _, y in points), max(y for _, y in points)
    west, east = min(x for x, _ in points), max(x for x, _ in points)
    pad_lat = MARGIN_KM / 110.57
    pad_lon = MARGIN_KM / (cos(radians((south + north) / 2)) * 111.32)
    return south - pad_lat, west - pad_lon, north + pad_lat, east + pad_lon


def center(provinces: tuple[str, ...] = AREA_PROVINCES) -> tuple[float, float]:
    south, west, north, east = bounds(tuple(provinces))
    return (south + north) / 2, (west + east) / 2


def radius_km(provinces: tuple[str, ...] = AREA_PROVINCES) -> float:
    """Straal van een cirkel om het midden die het hele werkgebied bevat (voor zoekdiensten die
    alleen een cirkel kennen; daarna altijd in_area gebruiken)."""
    south, west, north, east = bounds(tuple(provinces))
    lat, lon = center(tuple(provinces))
    return max(distance_km(lat, lon, y, x) for y in (south, north) for x in (west, east))


@lru_cache(maxsize=None)
def _province_info(provinces: tuple[str, ...] = AREA_PROVINCES) -> tuple[dict, ...]:
    data = json.loads(PROVINCES_PATH.read_text(encoding="utf-8"))["provincies"]
    return tuple({"naam": name, "iso": data[name]["iso"], "wikidata": data[name]["wikidata"]} for name in provinces)


def iso_codes(provinces: tuple[str, ...] = AREA_PROVINCES) -> list[str]:
    """ISO-codes van de provincies (NL-GR, ...), zoals OpenStreetMap ze kent."""
    return [p["iso"] for p in _province_info(tuple(provinces))]


def wikidata_ids(provinces: tuple[str, ...] = AREA_PROVINCES) -> list[str]:
    """Wikidata-nummers van de provincies (Q752, ...)."""
    return [p["wikidata"] for p in _province_info(tuple(provinces))]


def describe() -> dict:
    """Het werkgebied in het verslag (status.json)."""
    lat, lon = center()
    return {"naam": AREA_LABEL, "provincies": list(AREA_PROVINCES), "randKm": MARGIN_KM,
            "center": [round(lat, 4), round(lon, 4)], "radiusKm": round(radius_km())}
