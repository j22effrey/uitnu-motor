"""Agenda's ophalen binnen de tijd: na het budget afronden met wat er is, zonder uitjes kwijt te raken."""
import time
from datetime import date

from collector.active_source_runner import run_all
from collector.site_crawler import TIME_UP, CrawlResult, CrawlSource, Fetched, crawl_source
from pipeline.build_auto_events import build_auto_events

TODAY = date(2026, 10, 12)


def test_crawler_haalt_na_de_deadline_geen_paginas_meer_op():
    fetched = []

    def fetcher(url, timeout=15):
        fetched.append(url)
        return Fetched(url, 404, "text/plain", "")

    source = CrawlSource(id="x", name="X", root_url="https://podium.example/")
    result = crawl_source(source, fetcher=fetcher, deadline=time.monotonic() - 1)
    assert fetched == [] and result.errors == [TIME_UP]


def test_bronnen_krijgen_de_deadline_mee_en_melden_tijd_op():
    seen = {}

    def site_runner(source, timeout=15, deadline=None):
        seen[source.id] = deadline
        return CrawlResult(errors=[TIME_UP] if source.id == "traag" else [])

    sources = [{"id": "snel", "rootUrl": "https://snel.example/", "extractorHint": "jsonld_event"},
               {"id": "traag", "rootUrl": "https://traag.example/", "extractorHint": "jsonld_event"}]
    results = run_all(sources, site_runner=site_runner, budget_seconds=600)
    assert all(deadline is not None for deadline in seen.values())
    assert results["traag"].diagnostics.get("tijdOp") and not results["snel"].diagnostics.get("tijdOp")
    # Zonder budget: geen deadline (zoals vroeger).
    run_all(sources[:1], site_runner=lambda source, timeout=15: CrawlResult())
    # Elke bron hoogstens zoveel tijd, ook binnen een ruim budget.
    seen.clear()
    start = time.monotonic()
    run_all(sources, site_runner=site_runner, budget_seconds=3600, source_seconds=60)
    assert all(start < deadline <= time.monotonic() + 60 for deadline in seen.values())


def _record(title, url, day="2026-10-20"):
    return {"id": title, "title": title, "startDate": day, "time": "20:00", "city": "Assen", "sourceUrl": url}


def test_bron_die_niet_af_kwam_houdt_zijn_uitjes_van_de_vorige_keer():
    staged = {"canonical_publishable": [], "source_runs": {
        "traag": {"rootUrl": "https://www.traag.example/agenda/", "complete": False},
        "klaar": {"rootUrl": "https://klaar.example/", "complete": True},
    }}
    previous = [
        _record("Concert in de kerk", "https://traag.example/agenda/concert"),      # bron niet af: blijft
        _record("Oud uitje", "https://traag.example/agenda/oud", day="2026-10-01"),  # voorbij: weg
        _record("Lezing", "https://klaar.example/lezing"),                          # bron af: de nieuwe lijst telt
    ]
    out = build_auto_events([], staged, today=TODAY, previous=previous)
    assert [r["title"] for r in out] == ["Concert in de kerk"]
    # Staat hetzelfde uitje al in de handmatige agenda, dan niet dubbel.
    assert build_auto_events([_record("Concert in de kerk", "https://x.example/")], staged, today=TODAY,
                             previous=previous) == []


def test_website_die_niet_te_lezen_was_houdt_zijn_uitjes():
    from types import SimpleNamespace
    from pipeline.stage_active_sources import read_ok
    run = lambda error=None, **diagnostics: SimpleNamespace(error=error, diagnostics=diagnostics)
    # robots.txt of de website even onbereikbaar: geen enkele pagina gelezen, dus geen lege agenda.
    assert not read_ok(run(pages_visited=0, errors=["robots_unavailable_or_denied"]))
    assert not read_ok(run(error="timeout"))
    assert not read_ok(run(pages_visited=3, tijdOp=True))
    # Wel gelezen, ook als er (nu) geen uitjes op staan; en bronnen zonder paginatelling (een feed).
    assert read_ok(run(pages_visited=2, errors=[]))
    assert read_ok(run())
