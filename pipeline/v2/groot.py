"""Grote evenementen: uitjes die veel publiek trekken, waarvoor vaak iets wordt afgezet of opgebouwd.

De site licht ze uit, zodat niemand ze mist (afspraak met de eigenaar, 3 november 2026: 'gisteren was Adrillen in
Winschoten en ik kwam er te laat achter'). Elke uitkomst heeft een reden, net als de indeling in soorten.

Volgorde van beslissen:
1. het register (pipeline/v2/groot.json): een vaste naam, ja of nee, altijd met reden;
2. een groot evenement over de grens (grensregister): die staan er alleen in omdat ze groot zijn;
3. betaald voetbal of topsport in een stadion of op een circuit;
4. een echt festival (soort 'festival': groot terrein, meerdere podia) met 'festival' in de naam;
5. een naam die een publiekstrekker noemt (jaarmarkt, kermis, intocht, braderie, optocht, Koningsdag, marathon,
   skûtsjesilen, ...), maar alleen bij een soort die buiten of op straat kan (niet een voorstelling die 'kermis' in de
   titel heeft) en niet als het iets kleins is (lampionnenoptocht, rommelmarkt, kinderkermis).
Een uitje dat vaak terugkomt (elke week een braderie) is niet bijzonder genoeg om uit te lichten.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .classify import normalize

HERE = Path(__file__).parent

# Een stadion of circuit: een wedstrijd daar trekt tienduizenden mensen, met verkeersmaatregelen.
STADIUM = re.compile(r"\beuroborg\b|abe lenstra|cambuur ?stadion|\bde kooi\b|tt circuit|\bthialf\b")
# Een wedstrijd ('FC Groningen – Feyenoord'); ijshockey en basketbal in een hal zijn kleiner.
MATCH = re.compile(r"\s[-–]\s")
SMALL_MATCH = re.compile(r"jumbo flyers|capitals|ijshockey|\bdonar\b|basketbal|\bdames\b|\bvrouwen\b|\bjo\d|\bmo\d|onder \d+")

CROWD = re.compile(
    r"\bjaarmarkt|\bkermis\b|\bintocht\b|\bbraderie\b|\boptocht\b|\bcorso\b|koningsdag|koningsnacht|bevrijdingsfestival"
    r"|\bairshow\b|vuurwerk|\bmarathon\b|\btriathlon\b|wielerronde|motorcross|autocross|harddraverij"
    r"|skutsjesilen|\bsks\b|sneekweek|elfstedentocht|\btt assen\b|wereldbeker|world cup|\bfeestweek\b|\bmerke\b"
    r"|paardenmarkt|allerheiligenmarkt")
# Zo heet het, maar het is klein of voor een klein publiek.
NOT_CROWD = re.compile(
    r"lampion|sint ?maarten|st\.? ?maarten|kinderkermis|minikermis|kermisbingo|vlooienmarkt|rommelmarkt|snuffelmarkt"
    r"|workshop|lezing|\bfilm\b|expositie|tentoonstelling|\bquiz\b|\bbingo\b|spelletjes|optochtwagen|bouwen aan|knutsel"
    r"|vergadering|informatieavond|\bloterij\b|playbackshow")
# Soorten waarbij zo'n naam echt een publiekstrekker op straat of op een terrein is.
CROWD_KINDS = {"feest", "markt", "sport", "festival", "natuur", "kinderen", "overig"}
FESTIVAL_NAME = re.compile(r"festival|\bfest\b|festijn")
# Zo vaak in de agenda (zelfde naam en plaats) is het een vaste markt, geen bijzonder evenement.
OFTEN = 4


def load_register(path: Path | None = None) -> list[tuple[re.Pattern[str], bool, str]]:
    path = path or HERE / "groot.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for entry in raw.get("namen") or []:
        if isinstance(entry, dict) and entry.get("naam") and isinstance(entry.get("groot"), bool):
            out.append((re.compile(normalize(entry["naam"])), entry["groot"], entry.get("reden") or "vaste regel op naam"))
    return out


def _key(event: dict) -> tuple[str, str]:
    return normalize(event.get("title")), normalize((event.get("venue") or {}).get("city"))


def often(events: list[dict]) -> set[tuple[str, str]]:
    """Naam en plaats die op veel verschillende dagen in de agenda staan."""
    days: dict[tuple[str, str], set[str]] = {}
    for event in events:
        for occ in event.get("occurrences") or []:
            days.setdefault(_key(event), set()).add(occ.get("date") or "")
    return {key for key, found in days.items() if len(found) >= OFTEN}


def groot_reason(event: dict, register: list | None = None, frequent: set | None = None) -> str | None:
    """De reden waarom dit uitje groot is, of None."""
    title = normalize(event.get("title"))
    venue = normalize((event.get("venue") or {}).get("name"))
    for pattern, verdict, reason in register or []:
        if pattern.search(title):
            return reason if verdict else None
    if event.get("grensUitje"):
        return "groot evenement over de grens (grensregister)"
    if frequent and _key(event) in frequent:
        return None
    if STADIUM.search(venue) and MATCH.search(event.get("title") or "") and not SMALL_MATCH.search(title):
        return f"wedstrijd in {event['venue'].get('name')}: veel publiek en verkeersmaatregelen"
    kind = event.get("kind")
    if kind == "festival" and FESTIVAL_NAME.search(title):
        return "festival: groot terrein of meerdere zalen, meerdere podia"
    hit = CROWD.search(title)
    if hit and kind in CROWD_KINDS and not NOT_CROWD.search(title):
        return f"publiekstrekker: '{hit.group(0)}'"
    return None


def mark(events: list[dict], register: list | None = None) -> int:
    """Zet de soort 'groot' bij de tags en de reden in 'groot'. Geeft het aantal terug."""
    register = load_register() if register is None else register
    frequent = often(events)
    count = 0
    for event in events:
        reason = groot_reason(event, register, frequent)
        event.pop("groot", None)
        if reason:
            event["groot"] = reason
            event["tags"] = sorted(set(event.get("tags") or []) | {"groot"})
            count += 1
        elif "groot" in (event.get("tags") or []):
            event["tags"] = [t for t in event["tags"] if t != "groot"]
    return count


def summary(events: list[dict]) -> dict:
    """Voor status.json: hoeveel, en waarom (de eerste woorden van de reden)."""
    reasons = Counter((e.get("groot") or "").split(":")[0] for e in events if e.get("groot"))
    return {"aantal": sum(reasons.values()), "redenen": dict(reasons.most_common())}
