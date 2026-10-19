"""Conservative place inference for organizer events whose feed omits location.

Only short title prefixes/suffixes that PDOK identifies exactly as a Dutch
woonplaats/plaats are accepted. This is a fallback after structured extraction,
not a general text geocoder.
"""
from __future__ import annotations

from dataclasses import replace
from html import unescape
import re

from pipeline.event_model import RawEvent

GENERIC_SUFFIXES = {
    "event", "festival", "markt", "braderie", "vlooienmarkt", "concert",
    "show", "feest", "fair", "beurs", "dag", "dagen", "week", "weekend",
}
ALLOWED_TYPES = {"woonplaats", "plaats"}


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def title_place_candidates(title: str, max_words: int = 3) -> list[str]:
    original = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’-]*", unescape(title or ""))
    if not original:
        return []

    out: list[str] = []

    # Many Dutch event organisers prefix titles with the town, e.g.
    # "Groningen Stadjersmarkt" or "Assen Drentse vlooienmarkt".
    for size in range(min(max_words, len(original)), 0, -1):
        candidate = " ".join(original[:size]).strip()
        if candidate.casefold() not in GENERIC_SUFFIXES and candidate not in out:
            out.append(candidate)

    # Existing suffix strategy remains useful for titles such as
    # "Braderie en vlooienmarkt Eurohal Zuidbroek".
    words = list(original)
    while words and (words[-1].casefold() in GENERIC_SUFFIXES or re.fullmatch(r"20\d{2}", words[-1])):
        words.pop()
    for size in range(min(max_words, len(words)), 0, -1):
        candidate = " ".join(words[-size:]).strip()
        if candidate.casefold() in GENERIC_SUFFIXES:
            continue
        if candidate not in out:
            out.append(candidate)
    return out


def infer_title_place(event: RawEvent, *, geocode_fn=None, timeout: float = 8) -> RawEvent:
    if event.city or (event.lat is not None and event.lon is not None):
        return event
    if geocode_fn is None:
        from collector.pdok_geocode import geocode as geocode_fn
    for candidate in title_place_candidates(event.title):
        try:
            results = geocode_fn(candidate, rows=6, timeout=timeout)
        except Exception:
            continue
        want = _norm(candidate)
        for result in results:
            if (result.type or "").casefold() not in ALLOWED_TYPES:
                continue
            label_head = (result.label or "").split(",", 1)[0]
            if _norm(label_head) != want:
                continue
            raw = dict(event.raw or {})
            raw["title_place_inference"] = {
                "candidate": candidate,
                "pdok_label": result.label,
                "pdok_type": result.type,
            }
            return replace(event, city=label_head.strip(), lat=result.lat, lon=result.lon, raw=raw)
    return event


def locate_city(event: RawEvent, *, geocode_fn=None, timeout: float = 8) -> RawEvent:
    """Coördinaten van de plaats opzoeken als alleen de plaatsnaam bekend is.

    Zo kan de fabriek controleren of het uitje binnen het werkgebied ligt.
    Alleen een exacte PDOK-woonplaats telt.
    """
    if not event.city or (event.lat is not None and event.lon is not None):
        return event
    if geocode_fn is None:
        from collector.pdok_geocode import geocode as geocode_fn
    want = _norm(event.city)
    province = _norm((event.raw or {}).get("provincie") or "")
    results = [r for r in geocode_fn(event.city, rows=6, timeout=timeout)
               if (r.type or "").casefold() in ALLOWED_TYPES and _norm((r.label or "").split(",", 1)[0]) == want]
    # Plaatsen met dezelfde naam (Zuidwolde in Groningen en in Drenthe): de provincie van de bron eerst.
    if province:
        results.sort(key=lambda r: _norm((r.label or "").rsplit(",", 1)[-1]) != province)
    for result in results:
        raw = dict(event.raw or {})
        raw["city_geocode"] = {"pdok_label": result.label, "pdok_type": result.type}
        return replace(event, lat=result.lat, lon=result.lon, raw=raw)
    return event
