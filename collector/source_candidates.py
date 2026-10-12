"""Durable queue for websites discovered by UITNU.

A candidate is only a lead. Discovery never activates a website as a trusted
source automatically. Robots, source policy and extraction quality are reviewed
separately before activation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse, urlunparse


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_url(value: str) -> str:
    p = urlparse(str(value or "").strip())
    if p.scheme not in {"http", "https"} or not p.hostname:
        return ""
    host = p.hostname.casefold()
    port = f":{p.port}" if p.port and not ((p.scheme == "https" and p.port == 443) or (p.scheme == "http" and p.port == 80)) else ""
    netloc = host + port
    path = p.path or "/"
    return urlunparse((p.scheme.casefold(), netloc, path, "", p.query, ""))


def host_key(value: str) -> str:
    url = canonical_url(value)
    host = (urlparse(url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _read(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload = payload.get("candidates", [])
    return [x for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []


def load_source_hosts(path: str | Path) -> set[str]:
    """Load already-configured crawler hosts so they do not re-enter the queue."""
    path = Path(path)
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    values = payload.get("sources", []) if isinstance(payload, dict) else []
    if not isinstance(values, list):
        return set()
    return {
        host_key(item.get("rootUrl") or item.get("root_url") or "")
        for item in values
        if isinstance(item, dict) and host_key(item.get("rootUrl") or item.get("root_url") or "")
    }


def filter_new_hosts(discoveries: Iterable[dict], known_hosts: Iterable[str]) -> list[dict]:
    """Drop discoveries for domains UITNU already has as configured sources."""
    known = {
        str(host or "").casefold().removeprefix("www.")
        for host in known_hosts
        if str(host or "").strip()
    }
    out: list[dict] = []
    for discovery in discoveries:
        if not isinstance(discovery, dict):
            continue
        host = host_key(discovery.get("url") or "")
        if host and host not in known:
            out.append(discovery)
    return out


def _evidence_key(value: dict) -> tuple[str, str, str]:
    return (
        str(value.get("kind") or ""),
        str(value.get("sourceId") or ""),
        str(value.get("fromUrl") or ""),
    )


def candidate_priority(item: dict) -> dict:
    """Compute an explainable value score; it never grants trust or activation.

    Repeated benchmark gaps are valuable because one organizer source can close
    multiple missing events. Technical support gets a modest boost so the queue
    favours sources we can actually ingest, while policy/robots blocks sink.
    """
    evidence = [x for x in item.get("evidence", []) if isinstance(x, dict)]
    benchmark_gaps = {
        (str(x.get("fromUrl") or ""), str(x.get("anchorText") or ""))
        for x in evidence
        if x.get("kind") == "benchmark_gap"
    }
    source_origins = {
        (str(x.get("kind") or ""), str(x.get("sourceId") or ""))
        for x in evidence
        if x.get("kind") or x.get("sourceId")
    }

    score = int(item.get("score") or 0)
    score += min(len(benchmark_gaps), 10) * 18
    score += min(len(source_origins), 5) * 4
    score += min(int(item.get("seenCount") or 0), 10) * 2

    probe = str(item.get("probeStatus") or "")
    if probe == "supported":
        score += 25
    elif probe == "blocked":
        score -= 80
    elif probe == "error":
        score -= 15

    if item.get("extractor") in {"wordpress_tribe", "jsonld_event", "ics", "html_agenda_dutch"}:
        score += 10
    if item.get("policyStatus") == "blocked":
        score -= 200
    if item.get("robotsStatus") == "blocked":
        score -= 150
    if item.get("activationStatus") in {"active", "approved-disabled"}:
        score -= 500

    return {
        "priorityScore": score,
        "benchmarkGapCount": len(benchmark_gaps),
        "evidenceSourceCount": len(source_origins),
    }


def _refresh_priority(item: dict) -> None:
    item.update(candidate_priority(item))


def merge_candidates(existing: Iterable[dict], discoveries: Iterable[dict], *, observed_at: str | None = None) -> list[dict]:
    """Merge discoveries by host while preserving human review/probe fields."""
    now = observed_at or utc_now()
    by_host: dict[str, dict] = {}

    for value in existing:
        if not isinstance(value, dict):
            continue
        host = str(value.get("host") or host_key(value.get("url") or "")).casefold()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            continue
        item = dict(value)
        item["host"] = host
        item.setdefault("id", host)
        item.setdefault("activationStatus", "candidate")
        item.setdefault("policyStatus", "review")
        item.setdefault("robotsStatus", "unchecked")
        item.setdefault("probeStatus", "pending")
        item.setdefault("extractor", None)
        item.setdefault("lastError", None)
        item.setdefault("evidence", [])
        item.setdefault("seenCount", 0)
        by_host[host] = item

    for discovery in discoveries:
        if not isinstance(discovery, dict):
            continue
        url = canonical_url(discovery.get("url") or "")
        host = host_key(url)
        if not host:
            continue
        score = int(discovery.get("score") or 0)
        item = by_host.get(host)
        if item is None:
            item = {
                "id": host,
                "host": host,
                "url": url,
                "score": score,
                "firstSeenAt": now,
                "lastSeenAt": now,
                "seenCount": 0,
                "activationStatus": "candidate",
                "policyStatus": "review",
                "robotsStatus": "unchecked",
                "probeStatus": "pending",
                "extractor": None,
                "lastError": None,
                "evidence": [],
            }
            by_host[host] = item
        item["lastSeenAt"] = now
        item["seenCount"] = int(item.get("seenCount") or 0) + 1
        if score > int(item.get("score") or 0):
            item["score"] = score
            item["url"] = url

        evidence = {
            "kind": str(discovery.get("kind") or "crawler"),
            "sourceId": str(discovery.get("source_id") or discovery.get("sourceId") or "") or None,
            "fromUrl": canonical_url(discovery.get("from_url") or discovery.get("fromUrl") or "") or None,
            "anchorText": str(discovery.get("anchor_text") or discovery.get("anchorText") or "")[:180] or None,
            "score": score,
            "seenAt": now,
        }
        if discovery.get("lat") is not None and discovery.get("lon") is not None:
            evidence["lat"], evidence["lon"] = discovery["lat"], discovery["lon"]
        same = next((x for x in item.get("evidence", [])
                     if isinstance(x, dict) and _evidence_key(x) == _evidence_key(evidence)), None)
        if same is None:
            item.setdefault("evidence", []).append(evidence)
            item["evidence"] = item["evidence"][-20:]
        elif "lat" in evidence:
            same["lat"], same["lon"] = evidence["lat"], evidence["lon"]

    for item in by_host.values():
        _refresh_priority(item)
    return sorted(
        by_host.values(),
        key=lambda x: (-int(x.get("priorityScore") or 0), -int(x.get("score") or 0), x["host"]),
    )


def refresh_queue_priorities(path: str | Path) -> list[dict]:
    """Re-score a queue after probes/policy changes without adding discoveries."""
    path = Path(path)
    values = _read(path)
    for item in values:
        _refresh_priority(item)
    values.sort(key=lambda x: (-int(x.get("priorityScore") or 0), -int(x.get("score") or 0), x.get("host", "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump({"version": 1, "candidates": values}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return values


def update_queue(path: str | Path, discoveries: Iterable[dict], *, observed_at: str | None = None) -> list[dict]:
    """Atomically persist discoveries and return the merged queue."""
    path = Path(path)
    merged = merge_candidates(_read(path), discoveries, observed_at=observed_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump({"version": 1, "candidates": merged}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return merged


def discoveries_from_crawl_results(results: dict) -> list[dict]:
    out: list[dict] = []
    for source_id, result in results.items():
        for candidate in getattr(result, "external_candidates", []) or []:
            out.append({
                "url": candidate.url,
                "from_url": candidate.from_url,
                "anchor_text": candidate.anchor_text,
                "score": candidate.score,
                "source_id": source_id,
                "kind": "crawler",
            })
    return out
