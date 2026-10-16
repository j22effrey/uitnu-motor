"""Wat misging bij het ophalen wordt bewaard (data/ophaalfouten.json), met sinds wanneer."""
from datetime import datetime, timezone

from pipeline.stage_active_sources import update_error_log

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def test_fouten_met_sinds_wanneer():
    staged = {"source_runs": {
        "vera": {"error": "HTTPError 403", "complete": False, "diagnostics": {}},
        "spot": {"error": None, "complete": True, "diagnostics": {}},
        "klein": {"error": None, "complete": False, "diagnostics": {"onlangsGelezen": True}},
        "traag": {"error": None, "complete": False, "diagnostics": {"tijdOp": True}},
        "plat": {"error": None, "complete": False, "diagnostics": {"pages_visited": 0}},
    }}
    previous = {"vera": {"fout": "HTTPError 403", "sinds": "2026-10-14T09:00+00:00"}, "spot": {"sinds": "x"}}
    log = update_error_log(previous, staged, NOW)
    assert set(log) == {"vera", "traag", "plat"}
    assert log["vera"]["sinds"] == "2026-10-14T09:00+00:00"
    assert log["vera"]["laatst"] == "2026-10-16T12:00+00:00"
    assert log["traag"]["fout"] == "de tijd was op"
    assert "robots" in log["plat"]["fout"]
