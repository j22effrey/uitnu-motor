"""Stage active source output through quality gates without publishing it.

The staging layer is intentionally write-free: it enriches only conservatively,
classifies raw events with existing publishability rules, deduplicates publishable
records, and exposes a review queue. A separate future promotion step may update
public data only after this stage is proven stable.
"""
from __future__ import annotations

from dataclasses import asdict
import argparse
import json
import time

from collector.active_source_runner import SourceRunResult, load_active_sources, run_all
from collector.title_place_inference import infer_title_place, locate_city
from pipeline.dedupe import dedupe
from pipeline.publishability import decide


def enrich_results(
    results: dict[str, SourceRunResult],
    *,
    infer_fn=infer_title_place,
    geocode_fn=None,
    timeout: float = 8,
    deadline: float | None = None,
) -> dict[str, SourceRunResult]:
    """Conservatively fill missing places and cache repeated geocode queries.

    Na de deadline (time.monotonic()) wordt er niets meer opgezocht: de uitjes blijven zoals ze zijn."""
    if geocode_fn is None:
        from collector.pdok_geocode import geocode as geocode_fn

    cache: dict[tuple[str, int], list] = {}

    def cached_geocode(query, rows=6, timeout=8):
        key = (str(query).casefold().strip(), int(rows))
        if key not in cache:
            cache[key] = geocode_fn(query, rows=rows, timeout=timeout)
        return cache[key]

    enriched: dict[str, SourceRunResult] = {}
    for source_id, result in results.items():
        events = []
        for event in result.events:
            if deadline is not None and time.monotonic() >= deadline:
                events.append(event)
                continue
            try:
                event = infer_fn(event, geocode_fn=cached_geocode, timeout=timeout)
            except Exception:
                pass
            try:
                event = locate_city(event, geocode_fn=cached_geocode, timeout=timeout)
            except Exception:
                pass
            events.append(event)
        enriched[source_id] = SourceRunResult(
            source_id=result.source_id,
            extractor=result.extractor,
            events=events,
            diagnostics=result.diagnostics,
            error=result.error,
        )
    return enriched


def stage_results(results: dict[str, SourceRunResult]) -> dict:
    raw_events = []
    source_errors = {}
    for source_id, result in results.items():
        raw_events.extend(result.events)
        if result.error:
            source_errors[source_id] = result.error

    publishable = []
    review = []
    suppressed = []
    decisions = []
    for event in raw_events:
        decision = decide(event)
        record = {
            "event": asdict(event),
            "decision": asdict(decision),
        }
        decisions.append(record)
        if decision.action == "publish":
            publishable.append(event)
        elif decision.action == "suppress":
            suppressed.append(record)
        else:
            review.append(record)

    canonical = dedupe(publishable)
    return {
        "source_count": len(results),
        "source_errors": source_errors,
        "raw_event_count": len(raw_events),
        "publishable_raw_count": len(publishable),
        "canonical_publishable_count": len(canonical),
        "review_count": len(review),
        "suppressed_count": len(suppressed),
        "canonical_publishable": [asdict(x) for x in canonical],
        "review": review,
        "suppressed": suppressed,
        "decisions": decisions,
    }


SOURCE_SECONDS = 240  # hoogstens vier minuten per bron (met een tijdsbudget)


def read_ok(value) -> bool:
    """Is de agenda van deze bron echt gelezen? Niet bij een storing, als de tijd op was, of als er
    geen enkele pagina gelezen kon worden (robots.txt of de website was even onbereikbaar). Dan is
    'geen uitjes' geen lege agenda, en blijven de uitjes van de vorige keer staan."""
    diagnostics = value.diagnostics or {}
    if value.error or diagnostics.get("tijdOp"):
        return False
    return diagnostics.get("pages_visited") != 0


def run(*, sources_path: str, workers: int = 4, timeout: float = 15, budget_seconds: float | None = None) -> dict:
    """Alle bronnen ophalen en keuren. Met een tijdsbudget: ophalen krijgt het grootste deel, het
    opzoeken van plaatsen de rest; wat niet af is, telt niet als 'weg' (zie build_auto_events)."""
    started = time.monotonic()
    sources = load_active_sources(sources_path)
    roots = {str(s.get("id") or ""): str(s.get("rootUrl") or "") for s in sources}
    results = run_all(sources, workers=workers, timeout=timeout,
                      budget_seconds=budget_seconds * 0.75 if budget_seconds else None,
                      source_seconds=SOURCE_SECONDS if budget_seconds else None)
    deadline = started + budget_seconds if budget_seconds else None
    results = enrich_results(results, timeout=min(timeout, 8), deadline=deadline)
    staged = stage_results(results)
    staged["source_runs"] = {
        key: {
            "extractor": value.extractor,
            "rootUrl": roots.get(key, ""),
            "event_count": len(value.events),
            "diagnostics": value.diagnostics,
            "error": value.error,
            # Niet helemaal gelukt (storing, tijd op, niets te lezen): de vorige uitjes blijven staan.
            "complete": read_ok(value),
        }
        for key, value in results.items()
    }
    staged["seconds"] = round(time.monotonic() - started, 1)
    return staged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage active UITNU source output without publishing")
    parser.add_argument("--sources", default="collector/web_crawl_sources.json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--output")
    parser.add_argument("--budget-minutes", type=float, default=None,
                        help="na zoveel minuten afronden met wat er is (de rest houdt de uitjes van de vorige keer)")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = run(sources_path=args.sources, workers=args.workers, timeout=args.timeout,
                  budget_seconds=args.budget_minutes * 60 if args.budget_minutes else None)
    text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
