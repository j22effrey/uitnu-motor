"""Zet bronnen automatisch aan als ze aan alle eisen voldoen.

Eisen: de robot kan de agenda lezen, robots.txt staat het toe, de website ligt niet buiten
het werkgebied en is geen verzamelsite, wiki of social media. Dan gaat het om de eigen website
van een plek of organisator, en UITNU neemt daarvan alleen feiten over (geen teksten of foto's).

Draaien:  python -m collector.auto_activate
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from collector.discover_venues import is_excluded
from collector.source_activation import _atomic_write, activation_reasons, default_place_for, promote_candidate

NOTE = ("Automatisch goedgekeurd: eigen website van een plek of organisator binnen het werkgebied, "
        "met een agenda die de robot kan lezen. Alleen feiten, geen teksten of foto's.")


def name_for(candidate: dict) -> str:
    for evidence in candidate.get("evidence") or []:
        text = re.sub(r"\s*\([^)]*\)\s*$", "", str(evidence.get("anchorText") or "")).strip()
        if text and text != "naamloze plek":
            return text
    return candidate.get("host") or "Onbekende bron"


def role_for(candidate: dict) -> str:
    kinds = {e.get("kind") for e in candidate.get("evidence") or []}
    return "organizer" if "wikidata" in kinds and "osm" not in kinds else "venue"


def deep_page(url: str) -> bool:
    """Een pagina diep in een grote website (zoals een landelijke organisatie met een pagina per
    locatie). De agenda van zo'n site gaat over het hele land, niet over deze plek: niet automatisch."""
    return len([part for part in urlparse(url or "").path.split("/") if part]) >= 3


def eligible(candidate: dict) -> bool:
    return (candidate.get("activationStatus") in (None, "candidate")
            and candidate.get("probeStatus") == "supported"
            and candidate.get("robotsStatus") == "allowed"
            and candidate.get("policyStatus") != "blocked"
            and candidate.get("areaStatus") != "buiten"
            and not is_excluded(candidate.get("url") or "")
            and not deep_page(candidate.get("url") or ""))


def auto_activate(queue_path: str, sources_path: str, today: str | None = None) -> list[dict]:
    path = Path(queue_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    chosen = [c for c in payload.get("candidates", []) if isinstance(c, dict) and eligible(c)]
    for candidate in chosen:
        candidate["policyStatus"] = "allowed"
        candidate["policyReview"] = {"status": "allowed", "reviewedAt": today or date.today().isoformat(), "note": NOTE}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    activated = []
    for candidate in chosen:
        role = role_for(candidate)
        if activation_reasons(candidate, role=role):
            continue
        promote_candidate(queue_path=queue_path, sources_path=sources_path,
                          host=candidate["host"], name=name_for(candidate), role=role)
        activated.append({"host": candidate["host"], "name": name_for(candidate), "role": role})
    return activated


def fill_places(queue_path: str, sources_path: str) -> list[str]:
    """Actieve bronnen zonder vaste plaats die toch bij één dorp horen (een dorpswebsite, een tip of de
    officiële website van een dorp) krijgen die plaats alsnog, voor uitjes zonder eigen plaats."""
    queue = json.loads(Path(queue_path).read_text(encoding="utf-8"))
    by_host = {c.get("host"): c for c in queue.get("candidates", []) if isinstance(c, dict)}
    registry = json.loads(Path(sources_path).read_text(encoding="utf-8"))
    changed = []
    for source in registry.get("sources", []):
        if not isinstance(source, dict) or source.get("defaultPlace") or not source.get("enabled", True):
            continue
        host = urlparse(source.get("rootUrl") or "").hostname or ""
        candidate = by_host.get(host.removeprefix("www."))
        place = default_place_for(candidate, role="venue") if candidate else None
        if place:
            source["defaultPlace"] = place
            changed.append(f"{source.get('name')}: {place['city']}")
    if changed:
        _atomic_write(sources_path, registry)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UITNU: geschikte bronnen automatisch aanzetten")
    parser.add_argument("--queue", default="data/source_candidates.json")
    parser.add_argument("--sources", default="collector/web_crawl_sources.json")
    args = parser.parse_args(argv)
    activated = auto_activate(args.queue, args.sources)
    print(f"Nieuwe bronnen aangezet: {len(activated)}")
    for item in activated:
        print(f"  - {item['name']} ({item['host']})")
    placed = fill_places(args.queue, args.sources)
    if placed:
        print(f"Vaste plaats toegevoegd bij {len(placed)} bronnen: " + "; ".join(placed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
