"""Keuring: publiceer alleen als de cijfers kloppen.

Bij een afwijking blijft de vorige versie live en meldt de workflow het probleem.
De grenzen zijn een eerste voorstel en staan bewust bij elkaar, zodat ze makkelijk
bij te stellen zijn.
"""
from __future__ import annotations

from collections import Counter

MIN_SHARE_OF_PREVIOUS = 0.85   # minstens 85% van de vorige run
SOURCE_DROP_MIN = 10           # een bron met >= 10 evenementen mag niet ineens 0 geven
MAX_OVERIG_SHARE = 0.10        # hooguit 10% 'overig'
SMALL_DATASET = 20             # onder dit aantal zijn percentages niet zinvol


def _hosts(events: list[dict]) -> Counter:
    count: Counter = Counter()
    for event in events:
        for host in {s.get("host") for s in event.get("sources") or [] if s.get("host")}:
            count[host] += 1
    return count


def _still_running(event: dict, today: str) -> bool:
    return any((o.get("endDate") or o.get("date") or "") >= today for o in event.get("occurrences") or [])


def run_gate(new_events: list[dict], previous_events: list[dict] | None, today: str | None = None,
             retired_hosts: set[str] | None = None) -> dict:
    """Vergelijk met de vorige run. Evenementen die inmiddels voorbij zijn tellen niet mee:
    die verdwijnen vanzelf en zijn geen teken dat een bron kapot is. Een bron die bewust is
    uitgezet (retired_hosts: uit in de bronnenlijst, of een uitgesloten website) mag leeg raken."""
    if previous_events and today:
        previous_events = [e for e in previous_events if _still_running(e, today)]
    checks: list[dict] = []
    total = len(new_events)
    prev_total = len(previous_events or [])

    if previous_events and prev_total >= SMALL_DATASET:
        ok = total >= MIN_SHARE_OF_PREVIOUS * prev_total
        checks.append({"name": "aantal_tegenover_vorige_run", "passed": ok,
                       "detail": f"{total} nu, {prev_total} vorige keer (minimaal {MIN_SHARE_OF_PREVIOUS:.0%})"})
    else:
        checks.append({"name": "aantal_tegenover_vorige_run", "passed": True,
                       "detail": "geen of kleine vorige run; niet vergeleken"})

    if previous_events:
        before, now = _hosts(previous_events), _hosts(new_events)
        dropped = [h for h, n in before.items() if n >= SOURCE_DROP_MIN and now.get(h, 0) == 0
                   and h not in (retired_hosts or set())]
        checks.append({"name": "geen_bron_ineens_leeg", "passed": not dropped,
                       "detail": ", ".join(dropped) if dropped else "alle grote bronnen leveren nog"})

    if total >= SMALL_DATASET:
        overig = sum(1 for e in new_events if e.get("kind") == "overig")
        share = overig / total
        checks.append({"name": "overig_maximaal_10_procent", "passed": share <= MAX_OVERIG_SHARE,
                       "detail": f"{overig} van {total} ({share:.0%})"})

    incomplete = [e.get("id") for e in new_events
                  if not (e.get("occurrences") and e["occurrences"][0].get("date")
                          and e.get("venue", {}).get("city") and e.get("url"))]
    checks.append({"name": "velden_compleet", "passed": not incomplete,
                   "detail": ", ".join(incomplete[:10]) if incomplete else "datum, plaats en bron-URL overal aanwezig"})

    return {"passed": all(c["passed"] for c in checks), "checks": checks}
