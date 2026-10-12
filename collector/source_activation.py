"""Promote reviewed source candidates into UITNU's active source registry.

Discovery and probing are deliberately separate from activation. A candidate may
only become active after policy, robots, extractor capability and source role are
explicitly approved. This module never decides policy by itself.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse, urlunparse

from collector.source_candidates import canonical_url, host_key, utc_now
from pipeline.v2.kinds import OSM_KIND_HINTS

VALID_ROLES = {"organizer", "venue", "tourism", "discovery"}
VALID_EXTRACTORS = {"wordpress_tribe", "jsonld_event", "ics", "html_agenda_dutch"}


def _read_json(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _atomic_write(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def site_root(value: str) -> str:
    url = canonical_url(value)
    if not url:
        return ""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))


def source_id_for_host(host: str) -> str:
    host = host_key(f"https://{host}/") or host.casefold().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", host).strip("-")
    return f"{slug}-web" if slug else "candidate-web"


def extractor_config(candidate: dict) -> dict:
    """Freeze probe-discovered URLs needed to execute the chosen extractor."""
    extractor = candidate.get("extractor")
    details = candidate.get("probeDetails") if isinstance(candidate.get("probeDetails"), dict) else {}
    root = site_root(candidate.get("url") or "")

    if extractor == "ics":
        urls = details.get("ics_urls") if isinstance(details.get("ics_urls"), list) else []
        feed = canonical_url(urls[0]) if urls else ""
        return {"feedUrl": feed} if feed else {}
    if extractor == "wordpress_tribe":
        endpoint = canonical_url(details.get("wordpress_endpoint") or "")
        return {"endpointUrl": endpoint} if endpoint else {}
    if extractor == "html_agenda_dutch":
        agenda = details.get("html_agenda") if isinstance(details.get("html_agenda"), dict) else {}
        agenda_url = canonical_url(agenda.get("url") or "") or canonical_url(urljoin(root, "agenda/"))
        return {"agendaUrl": agenda_url} if agenda_url else {}
    return {}


_OSM_ANCHOR = re.compile(r"^(?P<name>.+?)\s*\((?P<kind>[^,()]+)(?:,\s*(?P<city>[^()]+))?\)\s*$")


def default_place_for(candidate: dict, *, role: str) -> dict | None:
    """De vaste plek van een bron, voor uitjes waarvan de agenda zelf geen plaats noemt.

    - Een podium uit OpenStreetMap: de naam van het podium en de plaats.
    - Een dorpswebsite of tip ('Dorpsbelangen Froombosch (tip, Froombosch)'): alleen de plaats,
      want de uitjes zijn op verschillende plekken in het dorp.
    Alleen voor role 'venue' en alleen als alle vermeldingen naar dezelfde plaats wijzen.
    Een organisatie met plekken in meerdere plaatsen krijgt geen vaste plek.
    """
    if role != "venue":
        return None
    places = []
    for evidence in candidate.get("evidence") or []:
        if not isinstance(evidence, dict) or evidence.get("kind") not in ("osm", "tip", "dorpssite"):
            continue
        match = _OSM_ANCHOR.match(str(evidence.get("anchorText") or ""))
        if match and match.group("city"):
            venue = match.group("name").strip() if evidence.get("kind") == "osm" else None
            places.append((venue, match.group("city").strip(), evidence.get("lat"), evidence.get("lon")))
    cities = {city.casefold() for _, city, _, _ in places}
    if len(cities) != 1:
        return None
    venues = {venue for venue, _, _, _ in places if venue}
    name, city, lat, lon = next((p for p in places if p[0]), places[0])
    place = {"venue": name, "city": city} if len(venues) == 1 else {"city": city}
    if lat is not None and lon is not None:
        place.update(lat=float(lat), lon=float(lon))
    return place


def kind_hint_for(candidate: dict) -> str | None:
    """Soort uitje dat bij deze plek past, uit het soort plek in OpenStreetMap ('theatre' -> theater).

    Alleen als alle vermeldingen op hetzelfde uitkomen; de fabriek gebruikt het pas als de titel niets zegt.
    """
    kinds = set()
    for evidence in candidate.get("evidence") or []:
        if not isinstance(evidence, dict) or evidence.get("kind") != "osm":
            continue
        match = _OSM_ANCHOR.match(str(evidence.get("anchorText") or ""))
        if match:
            kinds.add(OSM_KIND_HINTS.get(match.group("kind").strip()))
    return kinds.pop() if len(kinds) == 1 and None not in kinds else None


def activation_reasons(candidate: dict, *, role: str) -> list[str]:
    reasons: list[str] = []
    if role not in VALID_ROLES:
        reasons.append("invalid_role")
    if candidate.get("activationStatus") not in {None, "candidate"}:
        reasons.append("not_candidate")
    if candidate.get("policyStatus") != "allowed":
        reasons.append("policy_not_allowed")
    else:
        review = candidate.get("policyReview")
        if not isinstance(review, dict) or review.get("status") != "allowed":
            reasons.append("policy_review_missing")
        elif not str(review.get("reviewedAt") or "").strip() or not str(review.get("note") or "").strip():
            reasons.append("policy_review_incomplete")
    if candidate.get("robotsStatus") != "allowed":
        reasons.append("robots_not_allowed")
    if candidate.get("probeStatus") != "supported":
        reasons.append("probe_not_supported")
    extractor = candidate.get("extractor")
    if extractor not in VALID_EXTRACTORS:
        reasons.append("unsupported_extractor")
    elif extractor == "ics" and not extractor_config(candidate).get("feedUrl"):
        reasons.append("ics_feed_missing")
    if not host_key(candidate.get("url") or ""):
        reasons.append("invalid_url")
    return reasons


def _source_hosts(payload: dict) -> set[str]:
    values = payload.get("sources", [])
    if not isinstance(values, list):
        return set()
    return {
        host_key(item.get("rootUrl") or item.get("root_url") or "")
        for item in values
        if isinstance(item, dict) and host_key(item.get("rootUrl") or item.get("root_url") or "")
    }


def promote_candidate(
    *,
    queue_path: str | Path,
    sources_path: str | Path,
    host: str,
    name: str,
    role: str,
    source_id: str | None = None,
    enabled: bool = True,
) -> dict:
    queue_payload = _read_json(queue_path)
    sources_payload = _read_json(sources_path)
    candidates = queue_payload.get("candidates", [])
    sources = sources_payload.get("sources", [])
    if not isinstance(candidates, list) or not isinstance(sources, list):
        raise ValueError("invalid queue or source registry shape")

    wanted = host_key(f"https://{host}/") or host.casefold().removeprefix("www.")
    candidate = next(
        (
            item for item in candidates
            if isinstance(item, dict)
            and (item.get("host") or host_key(item.get("url") or "")).casefold().removeprefix("www.") == wanted
        ),
        None,
    )
    if candidate is None:
        raise ValueError(f"unknown source candidate: {host}")
    if wanted in _source_hosts(sources_payload):
        raise ValueError(f"source host already active: {wanted}")

    reasons = activation_reasons(candidate, role=role)
    if reasons:
        raise ValueError("source candidate is not eligible: " + ", ".join(reasons))

    root = site_root(candidate.get("url") or "")
    sid = source_id or source_id_for_host(wanted)
    if any(isinstance(item, dict) and item.get("id") == sid for item in sources):
        raise ValueError(f"source id already exists: {sid}")

    source = {
        "id": sid,
        "name": name.strip() or wanted,
        "rootUrl": root,
        "role": role,
        "enabled": bool(enabled),
        "maxPages": 40 if role in {"organizer", "venue"} else 30,
        "maxDepth": 3 if role in {"organizer", "venue"} else 2,
        "minDelaySeconds": 0.5,
        "extractorHint": candidate.get("extractor"),
        "extractorConfig": extractor_config(candidate),
        "activatedFromCandidate": wanted,
        **({"defaultPlace": place} if (place := default_place_for(candidate, role=role)) else {}),
        **({"kindHint": hint} if (hint := kind_hint_for(candidate)) else {}),
        "policyReviewedAt": candidate.get("policyReview", {}).get("reviewedAt"),
    }
    sources.append(source)
    sources_payload["sources"] = sources
    sources_payload["updated"] = date.today().isoformat()

    candidate["activationStatus"] = "active" if enabled else "approved-disabled"
    candidate["activatedSourceId"] = sid
    candidate["activatedRole"] = role
    candidate["activatedName"] = source["name"]
    candidate["activatedAt"] = utc_now()

    _atomic_write(sources_path, sources_payload)
    _atomic_write(queue_path, queue_payload)
    return {"source": source, "candidate": candidate}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Promote one reviewed UITNU source candidate")
    parser.add_argument("host")
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", required=True, choices=sorted(VALID_ROLES))
    parser.add_argument("--source-id")
    parser.add_argument("--queue", default="data/source_candidates.json")
    parser.add_argument("--sources", default="collector/web_crawl_sources.json")
    parser.add_argument("--disabled", action="store_true", help="Approve but keep source disabled")
    args = parser.parse_args()
    try:
        result = promote_candidate(
            queue_path=args.queue,
            sources_path=args.sources,
            host=args.host,
            name=args.name,
            role=args.role,
            source_id=args.source_id,
            enabled=not args.disabled,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
