"""Elke drie uur een ronde, zonder kleine websites vaker lastig te vallen: een agenda hooguit om de zes
uur ophalen, nieuwe plekken zoeken eens per week."""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import collector.discover_venues as dv
import pipeline.stage_active_sources as stage
from pipeline import area
from pipeline.build_auto_events import build_auto_events

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 13)


# ---------------------------------------------------------------- agenda's ophalen

def test_onlangs_gelezen_bron_wordt_overgeslagen():
    sources = [{"id": "vers"}, {"id": "oud"}, {"id": "nieuw"}, {"id": "kapot"}]
    log = {"vers": (NOW - timedelta(hours=3)).isoformat(), "oud": (NOW - timedelta(hours=6)).isoformat(),
           "kapot": "geen datum"}
    assert stage.recently_read(sources, log, 5, NOW) == {"vers"}
    # Zonder wachttijd (met de hand gestart): alles ophalen.
    assert stage.recently_read(sources, log, 0, NOW) == set()
    assert stage.recently_read(sources, log, None, NOW) == set()


def _fake_run(monkeypatch, sources, events_by_source):
    fetched = []

    def run_all(values, **kwargs):
        fetched.extend(s["id"] for s in values)
        return {s["id"]: SimpleNamespace(source_id=s["id"], extractor="jsonld_event",
                                         events=events_by_source.get(s["id"], []),
                                         diagnostics={"pages_visited": 2}, error=None) for s in values}

    monkeypatch.setattr(stage, "load_active_sources", lambda path: sources)
    monkeypatch.setattr(stage, "run_all", run_all)
    monkeypatch.setattr(stage, "enrich_results", lambda results, **kwargs: results)
    monkeypatch.setattr(stage, "stage_results", lambda results: {"canonical_publishable": []})
    return fetched


def test_ophalen_slaat_verse_bronnen_over_en_onthoudt_wanneer(monkeypatch):
    sources = [{"id": "podium", "rootUrl": "https://www.podium.example/"},
               {"id": "dorp", "rootUrl": "https://dorp.example/agenda"}]
    ticket = SimpleNamespace(source_url="https://tickets.example/concert")
    fetched = _fake_run(monkeypatch, sources, {"dorp": [ticket]})
    earlier = (NOW - timedelta(hours=2)).isoformat(timespec="minutes")
    log = {"podium": earlier, "weg": earlier}
    staged = stage.run(sources_path="x", fetch_log=log, fresh_hours=5, now=NOW)
    assert fetched == ["dorp"]
    runs = staged["source_runs"]
    assert runs["podium"]["complete"] is False and runs["podium"]["diagnostics"] == {"onlangsGelezen": True}
    assert runs["podium"]["rootUrl"] == "https://www.podium.example/"
    assert runs["dorp"]["complete"] is True
    # De verse bron houdt zijn tijd, de gelezen bron krijgt de tijd van nu, een oude bron gaat eruit.
    assert staged["fetch_log"] == {"dorp": NOW.isoformat(timespec="minutes"), "podium": earlier}
    # Welke bron vond welk uitje, ook als de link naar een kaartjeswebsite wijst.
    assert staged["origins"] == {"https://tickets.example/concert": "https://dorp.example/agenda"}


def test_bron_die_niet_af_kwam_krijgt_geen_nieuwe_tijd(monkeypatch):
    sources = [{"id": "traag", "rootUrl": "https://traag.example/"}]
    monkeypatch.setattr(stage, "load_active_sources", lambda path: sources)
    monkeypatch.setattr(stage, "run_all", lambda values, **kwargs: {"traag": SimpleNamespace(
        source_id="traag", extractor="x", events=[], diagnostics={"tijdOp": True}, error="tijd op")})
    monkeypatch.setattr(stage, "enrich_results", lambda results, **kwargs: results)
    monkeypatch.setattr(stage, "stage_results", lambda results: {"canonical_publishable": []})
    staged = stage.run(sources_path="x", fetch_log={}, fresh_hours=5, now=NOW)
    assert staged["fetch_log"] == {}  # volgende ronde weer aan de beurt


def test_overgeslagen_bron_houdt_ook_uitjes_met_een_kaartjeslink():
    staged = {"canonical_publishable": [], "source_runs": {
        "podium": {"rootUrl": "https://www.podium.example/", "complete": False},
    }}
    previous = [
        {"id": "a", "title": "Concert", "startDate": "2026-10-20", "time": "20:00", "city": "Assen",
         "sourceUrl": "https://tickets.example/concert", "sourceRoot": "https://www.podium.example/"},
        {"id": "b", "title": "Lezing", "startDate": "2026-10-21", "time": "20:00", "city": "Assen",
         "sourceUrl": "https://tickets.example/lezing", "sourceRoot": "https://andere.example/"},
    ]
    out = build_auto_events([], staged, today=TODAY, previous=previous)
    assert [r["title"] for r in out] == ["Concert"]


def test_nieuwe_uitjes_onthouden_hun_bron():
    staged = {"canonical_publishable": [{
        "id": "x", "title": "Concert", "start_at": "2026-10-20T20:00:00", "end_at": None, "venue": "Podium",
        "address": None, "city": "Assen", "lat": None, "lon": None, "category": None, "price_text": None,
        "verification_status": "organizer_confirmed", "source_count": 1,
        "source_urls": ["https://tickets.example/concert"], "source_ids": []}],
        "origins": {"https://tickets.example/concert": "https://www.podium.example/"}}
    out = build_auto_events([], staged, today=TODAY)
    assert out and out[0]["sourceRoot"] == "https://www.podium.example/"


# ---------------------------------------------------------------- nieuwe plekken zoeken

def _log(**dates):
    return {"werkgebied": list(area.AREA_PROVINCES), "gelukt": dates}


def test_zoeken_eens_per_week_per_bron():
    week_ago = (TODAY - timedelta(days=7)).isoformat()
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    all_recent = _log(**{name: yesterday for name in dv.search_names()})
    assert dv.searches_due(all_recent, 7, TODAY) == []
    # Zonder wachttijd (met de hand gestart): alles.
    assert dv.searches_due(all_recent, None, TODAY) == list(dv.search_names())
    # Een week geleden, of nog nooit gelukt (OpenStreetMap was plat voor Drenthe): weer aan de beurt.
    log = _log(**{"OpenStreetMap (Groningen)": yesterday, "OpenStreetMap (Fryslân)": yesterday,
                  "Wikidata (festivals)": week_ago, "Wikidata (dorpen en gemeenten)": yesterday})
    assert dv.searches_due(log, 7, TODAY) == ["OpenStreetMap (Drenthe)", "Wikidata (festivals)"]


def test_nieuw_werkgebied_zoekt_meteen_alles():
    log = {"werkgebied": ["Groningen"], "gelukt": {name: TODAY.isoformat() for name in dv.search_names()}}
    assert dv.searches_due(log, 7, TODAY) == list(dv.search_names())
    assert dv.searches_due({}, 7, TODAY) == list(dv.search_names())


def test_zoeklog_begint_schoon_bij_een_nieuw_werkgebied(tmp_path):
    path = tmp_path / "zoekronde.json"
    old = {"werkgebied": ["Groningen"], "gelukt": {name: "2026-10-01" for name in dv.search_names()}}
    saved = dv.save_search_log(path, old, ["OpenStreetMap (Drenthe)"], TODAY)
    # De andere bronnen hebben voor dit werkgebied nog niet gezocht: die blijven aan de beurt.
    assert saved == {"werkgebied": list(area.AREA_PROVINCES), "gelukt": {"OpenStreetMap (Drenthe)": "2026-10-13"}}
    assert json.loads(path.read_text()) == saved


def test_motor_vraagt_niets_als_de_vorige_zoekronde_vers_is(tmp_path, monkeypatch):
    def no_network(*args):
        raise AssertionError("niet zoeken: de vorige keer is te kort geleden")

    for name in ("fetch_overpass", "fetch_wikidata", "fetch_wikidata_places"):
        monkeypatch.setattr(dv, name, no_network)
    queue, known = tmp_path / "queue.json", tmp_path / "known.json"
    queue.write_text(json.dumps({"version": 1, "candidates": []}))
    known.write_text(json.dumps({"sources": []}))
    (tmp_path / "zoekronde.json").write_text(json.dumps(_log(**{name: date.today().isoformat()
                                                              for name in dv.search_names()})))
    assert dv.main(["--queue", str(queue), "--known", str(known), "--every-days", "7",
                    "--tips", str(tmp_path / "geen-tips.json"),
                    "--village-sites", str(tmp_path / "geen-dorpssites.json")]) == 0


def test_motor_onthoudt_welke_zoekbronnen_lukten(tmp_path, monkeypatch):
    def overpass(provinces):
        if provinces == ("Drenthe",):
            raise OSError("Overpass is even plat")
        return {"elements": []}

    monkeypatch.setattr(dv, "fetch_overpass", overpass)
    monkeypatch.setattr(dv, "fetch_wikidata", lambda: {"results": {"bindings": []}})
    monkeypatch.setattr(dv, "fetch_wikidata_places", lambda: {"results": {"bindings": []}})
    queue, known = tmp_path / "queue.json", tmp_path / "known.json"
    queue.write_text(json.dumps({"version": 1, "candidates": []}))
    known.write_text(json.dumps({"sources": []}))
    dv.main(["--queue", str(queue), "--known", str(known), "--every-days", "7",
             "--tips", str(tmp_path / "geen-tips.json"), "--village-sites", str(tmp_path / "geen-dorpssites.json")])
    log = json.loads((tmp_path / "zoekronde.json").read_text())
    assert set(log["gelukt"]) == {"OpenStreetMap (Groningen)", "OpenStreetMap (Fryslân)",
                                  "Wikidata (festivals)", "Wikidata (dorpen en gemeenten)"}
    # De volgende ronde probeert alleen Drenthe opnieuw.
    assert dv.searches_due(log, 7, date.today()) == ["OpenStreetMap (Drenthe)"]
