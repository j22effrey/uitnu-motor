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

from collector.active_source_runner import SourceRunResult, load_active_sources, run_all
from collector.title_place_inference import infer_title_place
from pipeline.dedupe import dedupe
from pipeline.publishability import decide


def enrich_results(
    results: dict[str, SourceRunResult],
    *,
    infer_fn=infer_title_place,
    geocode_fn=None,
    timeout: float = 8,
) -> dict[str, SourceRunResult]:
    """Conservatively fill missing places and cache repeated geocode queries."""
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
            try:
                events.append(infer_fn(event, geocode_fn=cached_geocode, timeout=timeout))
            except Exception:
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


def run(*, sources_path: str, workers: int = 4, timeout: float = 15) -> dict:
    sources = load_active_sources(sources_path)
    results = run_all(sources, workers=workers, timeout=timeout)
    results = enrich_results(results, timeout=min(timeout, 8))
    staged = stage_results(results)
    staged["source_runs"] = {
        key: {
            "extractor": value.extractor,
            "event_count": len(value.events),
            "diagnostics": value.diagnostics,
            "error": value.error,
        }
        for key, value in results.items()
    }
    return staged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage active UITNU source output without publishing")
    parser.add_argument("--sources", default="collector/web_crawl_sources.json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--output")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = run(sources_path=args.sources, workers=args.workers, timeout=args.timeout)
    text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
