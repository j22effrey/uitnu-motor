"""Dekking: staat alles erin wat er in een plaats zeker hoort?

De lijst staat in collector/dekking.json: per plaats de podia, clubs, festivals, musea, kerken met concerten
en grote sport, met hun website. Elke ronde telt de motor per plek hoeveel uitjes er de komende 90 dagen zijn
(verwacht90), of bij iets jaarlijks of de volgende editie erin staat. Wat ontbreekt of te weinig oplevert,
komt in status.json onder 'dekking'. Zo valt een gat op zonder dat iemand het hoeft te melden.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

WINDOW_DAYS = 90


def load_register(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
            if count == 0:
                missing.append(row)
            elif count < want:
                short.append(row)
            else:
                ok += 1
    return {"gecontroleerd": checked, "goed": ok, "ontbreekt": missing, "teWeinig": short}
