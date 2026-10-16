"""Stage active source output through quality gates without publishing it.

The staging layer is intentionally write-free: it enriches only conservatively,
classifies raw events with existing publishability rules, deduplicates publishable
records, and exposes a review queue. A separate future promotion step may update
public data only after this stage is proven stable.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import sys
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


def read_fetch_log(path: str | Path | None) -> dict:
    """Per bron: wanneer de agenda voor het laatst helemaal gelezen is (data/opgehaald.json)."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def recently_read(sources: list[dict], fetch_log: dict, fresh_hours: float | None, now: datetime) -> set[str]:
    """Bronnen die korter dan fresh_hours geleden helemaal gelezen zijn. Die slaat de motor deze ronde
    over, zodat een kleine website niet elke ronde bezoek krijgt; hun uitjes van de vorige keer
    blijven staan. Nieuwe bronnen en bronnen die de vorige keer niet af kwamen, zijn altijd aan de beurt."""
    if not fresh_hours:
        return set()
    out = set()
    for source in sources:
        sid = str(source.get("id") or "")
        try:
            last = datetime.fromisoformat(str(fetch_log.get(sid)))
        except ValueError:
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now - last < timedelta(hours=fresh_hours):
            out.add(sid)
    return out


def update_fetch_log(fetch_log: dict, staged: dict, now: datetime, active: set[str]) -> dict:
    """Bronnen die nu helemaal gelezen zijn krijgen de tijd van nu; bronnen die niet meer actief zijn
    gaan eruit."""
    log = {sid: when for sid, when in fetch_log.items() if sid in active}
    for sid, info in (staged.get("source_runs") or {}).items():
        if isinstance(info, dict) and info.get("complete"):
            log[sid] = now.isoformat(timespec="minutes")
    return dict(sorted(log.items()))


def run(*, sources_path: str, workers: int = 4, timeout: float = 15, budget_seconds: float | None = None,
        fetch_log: dict | None = None, fresh_hours: float | None = None, now: datetime | None = None) -> dict:
    """Alle bronnen ophalen en keuren. Met een tijdsbudget: ophalen krijgt het grootste deel, het
    opzoeken van plaatsen de rest; wat niet af is, telt niet als 'weg' (zie build_auto_events).
    Met fresh_hours worden bronnen die onlangs nog gelezen zijn overgeslagen (zie recently_read)."""
    started = time.monotonic()
    now = now or datetime.now(timezone.utc)
    sources = load_active_sources(sources_path)
    roots = {str(s.get("id") or ""): str(s.get("rootUrl") or "") for s in sources}
    fresh = recently_read(sources, fetch_log or {}, fresh_hours, now)
    results = run_all([s for s in sources if str(s.get("id") or "") not in fresh], workers=workers, timeout=timeout,
                      budget_seconds=budget_seconds * 0.75 if budget_seconds else None,
                      source_seconds=SOURCE_SECONDS if budget_seconds else None)
    deadline = started + budget_seconds if budget_seconds else None
    results = enrich_results(results, timeout=min(timeout, 8), deadline=deadline)
    staged = stage_results(results)
    # Welke bron vond welk uitje (de link kan naar een kaartjeswebsite wijzen): zo houdt een bron die
    # niet af kwam of werd overgeslagen precies zijn eigen uitjes (build_auto_events).
    staged["origins"] = {event.source_url: roots.get(key, "")
                         for key, value in results.items() for event in value.events if event.source_url}
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
    for key in sorted(fresh):
        # Onlangs nog gelezen: deze ronde niet opnieuw. Telt als 'niet af', dus de uitjes blijven staan.
        staged["source_runs"][key] = {"extractor": None, "rootUrl": roots.get(key, ""), "event_count": 0,
                                      "diagnostics": {"onlangsGelezen": True}, "error": None, "complete": False}
    staged["fetch_log"] = update_fetch_log(fetch_log or {}, staged, now, set(roots))
    staged["seconds"] = round(time.monotonic() - started, 1)
    return staged


def update_error_log(previous: dict, staged: dict, now: datetime) -> dict:
    """Per bron die deze ronde niet gelezen kon worden: wat er misging en sinds wanneer. Zo is te zien
    waarom een bron in de motor niets oplevert terwijl hij het elders wel doet (Vera, oktober 2026)."""
    stamp = now.strftime("%Y-%m-%dT%H:%M+00:00")
    log = {}
    for key, run in (staged.get("source_runs") or {}).items():
        diagnostics = run.get("diagnostics") or {}
        if run.get("complete") or diagnostics.get("onlangsGelezen"):
            continue
        if run.get("error"):
            reason = str(run["error"])[:300]
        elif diagnostics.get("tijdOp"):
            reason = "de tijd was op"
        else:
            reason = "geen enkele pagina gelezen (robots.txt of website onbereikbaar)"
        since = (previous.get(key) or {}).get("sinds") or stamp
        log[key] = {"fout": reason, "sinds": since, "laatst": stamp}
    return dict(sorted(log.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage active UITNU source output without publishing")
    parser.add_argument("--sources", default="collector/web_crawl_sources.json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--output")
    parser.add_argument("--budget-minutes", type=float, default=None,
                        help="na zoveel minuten afronden met wat er is (de rest houdt de uitjes van de vorige keer)")
    parser.add_argument("--fetch-log", help="per bron wanneer die voor het laatst helemaal gelezen is (wordt bijgewerkt)")
    parser.add_argument("--fresh-hours", type=float, default=None,
                        help="een bron die korter dan zoveel uur geleden gelezen is, deze ronde overslaan")
    parser.add_argument("--error-log", help="per bron die niet gelezen kon worden: de fout en sinds wanneer")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = run(sources_path=args.sources, workers=args.workers, timeout=args.timeout,
                  budget_seconds=args.budget_minutes * 60 if args.budget_minutes else None,
                  fetch_log=read_fetch_log(args.fetch_log), fresh_hours=args.fresh_hours)
    if args.fetch_log:
        Path(args.fetch_log).write_text(json.dumps(payload["fetch_log"], ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
    if args.error_log:
        previous = read_fetch_log(args.error_log)
        errors = update_error_log(previous, payload, datetime.now(timezone.utc))
        Path(args.error_log).write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runs = list(payload["source_runs"].values())
    skipped = sum(1 for r in runs if (r.get("diagnostics") or {}).get("onlangsGelezen"))
    print(f"Bronnen: {len(runs) - skipped} opgehaald, waarvan {sum(1 for r in runs if r.get('complete'))} "
          f"helemaal gelezen; {skipped} overgeslagen (onlangs nog gelezen).", file=sys.stderr)
    text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
