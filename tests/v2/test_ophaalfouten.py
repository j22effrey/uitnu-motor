"""Wat misging bij het ophalen wordt bewaard (data/ophaalfouten.json), met sinds wanneer."""
from datetime import datetime, timezone

from pipeline.stage_active_sources import update_error_log

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def test_fouten_met_sinds_wanneer():
    staged = {"source_runs": {
        "vera": {"error": "HTTPError 403", "complete": False, "diagnostics": {}},
        "spot": {"error": None, "complete": True, "diagnostics": {}},
        "klein": {"error": None, "complete": False, "diagnostics": {"onlangsGelezen": True}},
        "plat": {"error": None, "complete": False, "diagnostics": {"pages_visited": 0}},
    }}
    previous = {"vera": {"fout": "HTTPError 403", "sinds": "2026-10-14T09:00+00:00"},
                "spot": {"sinds": "x"}, "weg": {"sinds": "y"}}
    log = update_error_log(previous, staged, NOW)
    assert set(log) == {"vera", "plat"}          # weer goed gelezen of uit de lijst: weg uit het verslag
    assert log["vera"]["sinds"] == "2026-10-14T09:00+00:00"
    assert log["vera"]["laatst"] == "2026-10-16T12:00+00:00"
    assert log["plat"]["sinds"] == "2026-10-16T12:00+00:00"
    assert "robots" in log["plat"]["fout"]


def test_tijd_op_is_geen_storing_van_de_website():
    staged = {"source_runs": {"traag": {"error": "tijd op", "complete": False, "diagnostics": {"tijdOp": True}}}}
    assert update_error_log({}, staged, NOW) == {}


def test_leeg_of_verknoeid_bestand():
    assert update_error_log({}, {}, NOW) == {}
    staged = {"source_runs": {"vera": {"error": "403", "complete": False, "diagnostics": {}}}}
    assert update_error_log({"vera": "tekst"}, staged, NOW)["vera"]["sinds"] == "2026-10-16T12:00+00:00"
