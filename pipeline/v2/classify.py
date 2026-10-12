"""Eén indeling voor heel UITNU.

Regels, in deze volgorde:
1. handmatige correctie (overrides.json) wint altijd;
2. trefwoorden in titel en beschrijving, met vaste uitzonderingen;
3. een regel per locatie of bron (website van een podium);
4. de oude categorie van de bron als hint;
5. anders 'overig'.

Indelen labelt alleen: deze module laat nooit een evenement weg.
Elke uitkomst bevat methode, reden en zekerheid, zodat fouten na te speuren zijn.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .kinds import DISCIPLINE_HINTS, KINDS, LEGACY_HINTS


def normalize(text: str) -> str:
    """Kleine letters, zonder accenten en met enkele spaties."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _compile(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


# Trefwoorden per soort. Nederlandse samenstellingen ("stadswandeling") zijn de reden
# dat sommige patronen bewust zonder woordgrens aan het begin werken.
PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "film": _compile([r"\bfilm", r"bioscoop", r"cinema", r"filmhuis", r"documentaire"]),
    "sport": _compile([
        r"hardloop", r"(?<!ver)(?<!door)(?<!aan)(?<!uit)loop\b", r"run\b", r"\btrail", r"toertocht", r"\d+\s?(km|kilometer|mijl)\b", r"\bmijl\b", r"marathon",
        r"triatlon", r"wedstrijd", r"toernooi", r"regatta", r"roeiwedstrijd", r"schaats",
        r"wielren", r"mountainbike", r"\bmtb\b", r"voetbal", r"korfbal", r"handbal", r"hockey",
        r"zwemtocht", r"sportdag", r"\brace\b", r"obstacle",
    ]),
    "natuur": _compile([
        r"wandel", r"excursie", r"natuur", r"vogel", r"sterren", r"paddenstoel", r"wildpluk",
        r"kwelder", r"wadlo", r"boswachter", r"fietstocht", r"struin", r"nacht van de nacht",
        r"huifkar", r"landgoed",
    ]),
    "eten": _compile([
        r"culinair", r"food", r"proeverij", r"\bproeven\b", r"\bwijn", r"\bbier(?!run)", r"smaak",
        r"high tea", r"brunch", r"\bdiner\b", r"barbecue", r"\bbbq\b", r"kookworkshop",
        r"whisk(e)?y", r"cocktail", r"\bgin\b",
    ]),
    "markt": _compile([
        r"markt", r"(?<=\w)maart\b", r"braderie", r"beurs", r"fair\b", r"salon\b",
        r"reis ?event", r"reizen\b.*\bevent", r"rommel", r"vlooien", r"snuffel",
    ]),
    "feest": _compile([
        r"kermis", r"feest", r"koningsdag", r"koningsnacht", r"sinterklaas", r"intocht",
        r"carnaval", r"optocht", r"lampion", r"halloween", r"spooktocht", r"lichtjes",
        r"vuurwerk", r"oud en nieuw",
    ]),
    "theater": _compile([
        r"theater", r"voorstelling", r"toneel", r"cabaret", r"comedy", r"stand-?up",
        r"musical", r"\bopera\b", r"ballet", r"\bdans(voorstelling|theater)?\b",
        r"poppen(kast|theater)", r"circus",
    ]),
    "muziek": _compile([
        r"concert", r"\blive\b", r"band\b", r"\bkoor", r"koren", r"orkest", r"\bdj\b", r"optreden",
        r"gospel", r"fanfare", r"shanty", r"smartlap",
        r"clubnacht", r"\bparty\b", r"\bjazz", r"\bpop\b", r"\brock", r"\bblues", r"\bmetal\b",
        r"hip-?hop", r"techno", r"\bhouse\b", r"recital", r"\borgel", r"cantate", r"muziek",
        r"singer-?songwriter", r"\brave\b", r"taptoe",
    ]),
    "kunst": _compile([
        r"tentoonstelling", r"expositie", r"\bexpo\b", r"museum", r"galerie", r"\bkunst",
        r"atelier", r"monument", r"erfgoed", r"open kerk", r"kerkpad", r"rondleiding",
    ]),
    "lezing": _compile([
        r"lezing", r"workshop", r"cursus", r"masterclass", r"\bdebat\b",
        r"symposium", r"voorlees",
    ]),
}

# Volgorde waarin soorten winnen als meerdere trefwoorden passen.
PRIORITY = [
    "film", "sport", "lezing", "natuur", "eten", "markt", "feest", "theater", "muziek", "kunst",
]

FESTIVAL = re.compile(r"festival")
STAGES = re.compile(r"podia|podium|stages|line-?up")
CLUBNIGHT = re.compile(r"\bdj\b|clubnacht|\bparty\b|techno|\bhouse\b|\brave\b")
CHOIR_ORGAN = re.compile(r"\bkoor|koren|\borgel")
FREE = re.compile(r"gratis|vrije? entree|\bfree\b")
CHILDREN = re.compile(r"kinder|kids|familie|jeugd|peuter|kleuter|sinterklaas|speurtocht|speurwandeling|springkussen")
THEATER_FESTIVAL = re.compile(r"cabaret|theater|comedy|toneel")
OUTDOOR = re.compile(r"\bbuiten|openlucht|strand")

# Websites die vrijwel alleen een soort aanbieden. Alleen gebruikt als trefwoorden niets opleveren.
VENUE_RULES: dict[str, str] = {
    "simplon.nl": "muziek",
    "vera-groningen.nl": "muziek",
}


def _matches(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for kind, patterns in PATTERNS.items():
        hits = [m.group(0) for p in patterns if (m := p.search(text))]
        if hits:
            found[kind] = hits
    return found


def _host(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def _is_multiday(event: dict) -> bool:
    for occ in event.get("occurrences") or []:
        if occ.get("endDate") and occ.get("endDate") != occ.get("date"):
            return True
    return False


def classify(event: dict, overrides: dict[str, str] | None = None,
             venue_rules: dict[str, str] | None = None) -> dict:
    """Geeft {kind, tags, method, reason, confidence} terug.

    venue_rules: extra 'website -> soort' uit de bronnenlijst (veld kindHint), naast VENUE_RULES.
    """
    title = event.get("title") or ""
    text = normalize(" ".join([title, event.get("description") or ""]))
    tags: set[str] = set()

    price = normalize(event.get("price") or "")
    if FREE.search(price) or FREE.search(normalize(title)):
        tags.add("gratis")
    if CHILDREN.search(text):
        tags.add("kinderen")
    if _is_multiday(event):
        tags.add("meerdaags")
    if OUTDOOR.search(text):
        tags.add("buiten")

    def result(kind: str, method: str, reason: str, confidence: float) -> dict:
        if kind == "natuur":
            tags.add("buiten")
        return {
            "kind": kind,
            "tags": sorted(tags),
            "method": method,
            "reason": reason,
            "confidence": confidence,
        }

    # 1. Handmatige correctie
    if overrides and event.get("id") in overrides:
        kind = overrides[event["id"]]
        if kind in KINDS:
            return result(kind, "correctie", "handmatige correctie in overrides.json", 1.0)

    found = _matches(text)
    in_title = _matches(normalize(title))
    race = "sport" in found
    has_festival = bool(FESTIVAL.search(text))

    # 2a. Festivals: alleen 'festival' als het echt meerdaags of meerpodia is
    if has_festival:
        tags.add("festival")
        if "film" in in_title:
            return result("film", "trefwoord", "filmfestival telt als film", 0.9)
        if "eten" in in_title:
            return result("eten", "trefwoord", "festival met één discipline: eten", 0.85)
        if THEATER_FESTIVAL.search(normalize(title)) and not _is_multiday(event):
            return result("theater", "trefwoord", "één avond van een theaterfestival", 0.8)
        if _is_multiday(event) or STAGES.search(text):
            tags.discard("festival")
            return result("festival", "trefwoord", "festival, meerdaags of met meerdere podia", 0.85)
        if CLUBNIGHT.search(text):
            return result("muziek", "trefwoord", "één avond met dj of clubnacht: geen festival", 0.8)
        if CHOIR_ORGAN.search(text):
            return result("muziek", "trefwoord", "festival met één discipline: muziek", 0.8)
        tags.discard("festival")
        return result("festival", "trefwoord", "titel noemt het een festival", 0.7)

    # 2b. Wandelingen en excursies zijn natuur, behalve bij een echte wedstrijd
    if "natuur" in found and race:
        return result("sport", "trefwoord", f"wedstrijd ({found['sport'][0]}) in de natuur", 0.85)
    for kind in PRIORITY:
        if kind in found:
            return result(kind, "trefwoord", f"trefwoord '{found[kind][0]}'", 0.8)

    # 3. Locatie of bron
    rules = {**(venue_rules or {}), **VENUE_RULES}
    for url in (event.get("url"), *(s.get("url") for s in event.get("sources") or [])):
        kind = rules.get(_host(url or ""))
        if kind in KINDS:
            return result(kind, "locatie", f"website {_host(url or '')}", 0.7)

    # 4. Oude categorie of discipline als hint
    hint = LEGACY_HINTS.get(event.get("legacyCategory") or "")
    if hint:
        return result(hint, "bronhint", f"oude categorie '{event.get('legacyCategory')}'", 0.5)
    hint = DISCIPLINE_HINTS.get(event.get("legacyDiscipline") or "")
    if hint:
        return result(hint, "bronhint", f"discipline '{event.get('legacyDiscipline')}'", 0.5)

    # 5. Niets gevonden
    return result("overig", "geen", "geen trefwoord, locatie of hint", 0.2)
