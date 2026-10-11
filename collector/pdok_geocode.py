"""PDOK Locatieserver geocoder adapter.

Uses the public/free Dutch government geocoder. No API key required.
Kept intentionally small so it can be swapped for the newer PDOK Location API later.
"""
from __future__ import annotations
from dataclasses import dataclass
import json, re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"

@dataclass
class GeoResult:
    label: str
    lat: float
    lon: float
    type: str | None = None
    municipality: str | None = None
    province: str | None = None
    id: str | None = None


def build_url(query: str, rows: int = 8) -> str:
    return BASE + "?" + urlencode({"q": query, "rows": rows, "fl": "*"})


def _point(doc: dict) -> tuple[float, float] | None:
    # Locatieserver normally returns centroide_ll as WKT POINT(lon lat).
    wkt = doc.get("centroide_ll") or doc.get("centroide_rd")
    if isinstance(wkt, str):
        m = re.search(r"POINT\s*\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", wkt)
        if m and doc.get("centroide_ll"):
            return float(m.group(2)), float(m.group(1))
    # Be permissive for future JSON variants / fixtures.
    lat = doc.get("lat") or doc.get("latitude")
    lon = doc.get("lon") or doc.get("lng") or doc.get("longitude")
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    return None


def parse_response(payload: dict) -> list[GeoResult]:
    docs = (payload.get("response") or {}).get("docs") or payload.get("docs") or []
    out: list[GeoResult] = []
    for doc in docs:
        point = _point(doc)
        if not point:
            continue
        label = (doc.get("weergavenaam") or doc.get("display_name") or doc.get("woonplaatsnaam") or doc.get("naam") or "").strip()
        if not label:
            continue
        out.append(GeoResult(
            label=label,
            lat=point[0], lon=point[1],
            type=doc.get("type"), municipality=doc.get("gemeentenaam"),
            province=doc.get("provincienaam"), id=doc.get("id"),
        ))
    return out


def geocode(query: str, rows: int = 8, timeout: float = 10) -> list[GeoResult]:
    req = Request(build_url(query, rows), headers={"User-Agent": "UITNU-prototype/0.3"})
    with urlopen(req, timeout=timeout) as resp:
        return parse_response(json.load(resp))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--url-only", action="store_true")
    args = p.parse_args()
    if args.url_only:
        print(build_url(args.query))
    else:
        for item in geocode(args.query):
            print(item)
