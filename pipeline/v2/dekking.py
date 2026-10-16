"""Dekking: staat alles erin wat er in een plaats zeker hoort?

De lijst staat in collector/dekking.json: per plaats de podia, clubs, festivals, musea, kerken met concerten
en grote sport, met hun website. Elke ronde telt de motor per plek hoeveel uitjes er de komende 90 dagen zijn
(verwacht90), of bij iets jaarlijks of de volgende editie erin staat. Wat ontbreekt of te weinig oplevert,
komt in status.json onder 'dekking'. Zo valt een gat op zonder dat iemand het hoeft te melden.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

WINDOW_DAYS = 90


def load_register(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# Plekken die de motor zelf vond (OpenStreetMap en Wikidata, in data/source_candidates.json) en die er zeker
# in horen: podia, theaters, bioscopen, musea, pretparken, dierentuinen, evenementenlocaties en festivals.
# Zo geldt de controle voor elke plaats in het werkgebied, niet alleen voor de plaatsen met een eigen lijst.
AUTO_TYPES = {
    "theatre": ("theater", 90), "music_venue": ("podium", 90), "concert_hall": ("podium", 90), "arts_centre": ("cultuurcentrum", 90),
    "cinema": ("bioscoop", 90), "nightclub": ("club", 90), "events_venue": ("evenementenlocatie", 90),
    "museum": ("museum", None), "theme_park": ("pretpark", None), "zoo": ("dierentuin", None), "festival": ("festival", None),
}
WHY = {
    "no_supported_extractor": "de test vond geen leesbare agenda: uitzoeken waar het programma staat",
    "error": "de website gaf een storing bij de test",
    "blocked": "robots.txt of de website weigert de motor",
    "moved": "de website is verhuisd: nieuw adres nakijken",
    "pending": "nog niet getest",
}
ANCHOR = re.compile(r"^(.*) \(([a-z_]+)(?:, ([^)]+))?\)$")


def auto_register(candidates: dict | list, manual_hosts: set[str] = frozenset()) -> dict:
    """De lijst van plekken die de motor kent, per plaats (zonder de plekken die al met de hand op de lijst staan)."""
    rows = candidates.get("candidates", []) if isinstance(candidates, dict) else candidates or []
    places: dict[str, list[dict]] = {}
    for item in rows:
        if not isinstance(item, dict) or item.get("areaStatus") == "buiten":
            continue
        host = _host(item.get("host"))
        if not host or host in manual_hosts:
            continue
        for evidence in item.get("evidence") or []:
            m = ANCHOR.match(str(evidence.get("anchorText") or ""))
            if not m or m.group(2) not in AUTO_TYPES:
                continue
            label, window = AUTO_TYPES[m.group(2)]
            entry = {"naam": m.group(1), "type": label, "website": item.get("url"), "hosts": [host], "auto": True,
                     "status": item.get("activationStatus"), "test": item.get("probeStatus")}
            entry.update({"verwacht90": 1} if window else {"jaarlijks": True})
            places.setdefault(m.group(3) or "plaats onbekend", []).append(entry)
            break
    return {"plaatsen": places}


def merge_registers(*registers: dict) -> dict:
    out: dict[str, list[dict]] = {}
    for register in registers:
        for city, places in (register.get("plaatsen") or {}).items():
            out.setdefault(city, []).extend(places)
    return {"plaatsen": out}


def _host(value: str | None) -> str:
    return str(value or "").lower().removeprefix("www.")


def coverage(events: list[dict], register: dict, today: date) -> dict:
    """Per plek op de lijst: hoeveel uitjes, en of dat genoeg is."""
    until = (today + timedelta(days=WINDOW_DAYS)).isoformat()
    now = today.isoformat()
    by_host: dict[str, list[dict]] = {}
    for event in events:
        # Een bron of de link van het uitje: een met de hand toegevoegd uitje telt zo ook mee.
        hosts = {_host(s.get("host")) for s in event.get("sources") or [] if s.get("host")}
        hosts |= {_host(urlparse(u).netloc) for u in [event.get("url")] + [s.get("url") for s in event.get("sources") or []] if u}
        for host in hosts:
            by_host.setdefault(host, []).append(event)

    def upcoming(event: dict, *, window: bool) -> bool:
        for occ in event.get("occurrences") or []:
            last = occ.get("endDate") or occ.get("date") or ""
            if last >= now and (not window or (occ.get("date") or "") <= until):
                return True
        return False

    missing, short, ok = [], [], 0
    checked = 0
    for city, places in (register.get("plaatsen") or {}).items():
        for place in places:
            checked += 1
            found = {e["id"]: e for h in place.get("hosts") or [] for e in by_host.get(_host(h), [])}
            yearly = bool(place.get("jaarlijks"))
            count = sum(1 for e in found.values() if upcoming(e, window=not yearly))
            want = 1 if yearly else int(place.get("verwacht90") or 1)
            row = {"naam": place.get("naam"), "plaats": city, "website": place.get("website"),
                   "gevonden": count, "verwacht": want, "periode": "volgende editie" if yearly else f"{WINDOW_DAYS} dagen"}
            if place.get("auto"):
                row["type"] = place.get("type")
                if count == 0 and place.get("status") != "active":
                    row["waarom"] = WHY.get(str(place.get("test")), "nog geen bron")
            if count == 0:
                missing.append(row)
            elif count < want:
                short.append(row)
            else:
                ok += 1
    by_type: dict[str, dict] = {}
    for row in missing + short:
        if row.get("type"):
            by_type.setdefault(row["type"], {"ontbreekt": 0})["ontbreekt"] += 1
    # Eerst de plekken met een eigen lijst (de grote podia), dan de rest; zo blijft het verslag leesbaar.
    missing.sort(key=lambda r: (bool(r.get("type")), r["plaats"], r["naam"] or ""))
    return {"gecontroleerd": checked, "goed": ok, "ontbreekt": missing, "teWeinig": short, "ontbreektPerSoort": by_type}
