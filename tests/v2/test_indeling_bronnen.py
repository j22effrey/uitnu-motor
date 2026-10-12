"""Uitjes van nieuwe podia vallen niet meer in 'overig' (dan keurt de keuring de agenda af)."""
import json
from datetime import date

from collector.jsonld_events import parse_html
from collector.source_activation import kind_hint_for, promote_candidate
from pipeline.build_auto_events import _classify
from pipeline.v2.build import build, source_kinds
from pipeline.v2.classify import classify


def _v2(title, url="https://podium.example/x", **extra):
    return {"id": title, "title": title, "url": url, "sources": [{"url": url}],
            "occurrences": [{"date": "2026-11-01"}], **extra}


def test_schema_org_soort_wordt_bewaard():
    html = """<script type="application/ld+json">[
      {"@type": "MusicEvent", "name": "Fleddy Melculy", "startDate": "2026-11-14T20:00"},
      {"@type": ["Event", "TheaterEvent"], "name": "Wende", "startDate": "2026-11-15T20:00"},
      {"@type": "Event", "name": "Iets", "startDate": "2026-11-16"}]</script>"""
    assert [e.event_type for e in parse_html(html, "https://p.example/")] == ["MusicEvent", "TheaterEvent", None]


def test_soort_van_de_organisator_als_de_titel_niets_zegt():
    item = {"title": "Fleddy Melculy", "category": "MusicEvent", "source_urls": ["https://p.example/a"]}
    assert _classify(item)[0] == "muziek"
    assert _classify(dict(item, category="TheaterEvent"))[0:3:2] == ("cultuur", "theater")
    # Trefwoorden in de titel gaan voor: een kerstmarkt blijft een markt.
    assert _classify(dict(item, title="Kerstmarkt", category="MusicEvent"))[0] == "markt"
    # Bij Spot bepaalt de organisator de discipline als de titel niets zegt.
    spot = {"title": "Wende", "category": "TheaterEvent", "source_urls": ["https://www.spotgroningen.nl/x"]}
    assert _classify(spot)[2] == "theater"


def test_soort_per_podium_en_discipline_in_de_fabriek():
    rules = {"podium.example": "theater"}
    assert classify(_v2("Wende"), None, rules)["kind"] == "theater"
    assert classify(_v2("Wende"), None, rules)["method"] == "locatie"
    assert classify(_v2("Wende"))["kind"] == "overig"
    assert classify(_v2("Kerstmarkt Bunne"), None, rules)["kind"] == "markt"  # trefwoord gaat voor
    assert classify(_v2("Wende", legacyCategory="cultuur", legacyDiscipline="cabaret"))["kind"] == "theater"
    assert classify(_v2("Wende"), None, {"podium.example": "onzin"})["kind"] == "overig"


def test_soort_plek_uit_openstreetmap():
    assert kind_hint_for({"evidence": [{"kind": "osm", "anchorText": "De Melkfabriek (theatre, Bunne)"}]}) == "theater"
    assert kind_hint_for({"evidence": [{"kind": "osm", "anchorText": "Neushoorn (music_venue, Leeuwarden)"}]}) == "muziek"
    mixed = {"evidence": [{"kind": "osm", "anchorText": "A (museum, X)"}, {"kind": "osm", "anchorText": "B (theatre, X)"}]}
    assert kind_hint_for(mixed) is None
    assert kind_hint_for({"evidence": [{"kind": "osm", "anchorText": "Dorpshuis (community_centre, X)"}]}) is None
    assert kind_hint_for({"evidence": [{"kind": "wikidata", "anchorText": "Fest (festival)"}]}) is None


def test_nieuwe_bron_krijgt_soort_mee(tmp_path):
    queue, sources = tmp_path / "q.json", tmp_path / "s.json"
    queue.write_text(json.dumps({"candidates": [{
        "host": "melk.example", "url": "https://melk.example/", "activationStatus": "candidate",
        "policyStatus": "allowed", "policyReview": {"status": "allowed", "reviewedAt": "2026-10-12", "note": "ok"},
        "robotsStatus": "allowed", "probeStatus": "supported", "extractor": "jsonld_event",
        "evidence": [{"kind": "osm", "anchorText": "De Melkfabriek (theatre, Bunne)"}]}]}))
    sources.write_text(json.dumps({"sources": []}))
    source = promote_candidate(queue_path=queue, sources_path=sources, host="melk.example", name="De Melkfabriek", role="venue")["source"]
    assert source["kindHint"] == "theater"
    assert source_kinds(sources) == {"melk.example": "theater"}


def test_avond_van_gisteren_komt_nu_door_de_keuring(tmp_path):
    """Nagespeeld: veel uitjes van nieuwe podia zonder trefwoord in de titel (bandnamen, voorstellingen)."""
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    rows = []
    for i in range(22):
        url = f"https://{'melk' if i % 2 else 'neushoorn'}.example/{i}"
        rows.append({"id": f"p{i}", "title": f"Artiest {i}", "startDate": "2026-11-01", "city": "Bunne",
                     "verificationStatus": "organizer_confirmed", "eventUrl": url, "sourceUrl": url})
    for i in range(30):
        url = f"https://markt.example/{i}"
        rows.append({"id": f"m{i}", "title": f"Braderie {i}", "startDate": "2026-11-02", "city": "Assen",
                     "verificationStatus": "organizer_confirmed", "eventUrl": url, "sourceUrl": url})
    (data / "events.json").write_text(json.dumps(rows))
    today = date(2026, 10, 12)

    _, before = build(data, out, today, {}, photo_cache={})
    assert not before["gate"]["passed"]  # zonder hints: 22 van 52 'overig'

    kinds = {"melk.example": "theater", "neushoorn.example": "muziek"}
    events, after = build(data, out, today, {}, photo_cache={}, venue_kinds=kinds)
    assert after["gate"]["passed"]
    assert after["byKind"] == {"markt": 30, "theater": 11, "muziek": 11}
    assert all("legacyDiscipline" not in e for e in events)


def test_uitjes_zonder_zaal_in_verschillende_plaatsen_blijven_apart():
    from pipeline.v2.convert import merge_duplicates
    def event(title, city):
        return {"id": title, "title": title, "venue": {"name": None, "city": city},
                "occurrences": [{"date": "2026-12-12", "endDate": None, "startTime": None}],
                "sources": [{"url": f"https://{city}.example/"}], "tags": [], "url": f"https://{city}.example/"}
    merged = merge_duplicates([event("Kerstmarkt Haren", "Haren"), event("Kerstmarkt Assen", "Assen")])
    assert len(merged) == 2


def test_pagina_van_de_organisator_geeft_soort_zonder_tekst_te_bewaren():
    from collector.event_photos import page_facts
    html = """<html><head><meta name="description" content="Het grootste springkussenfestijn voor kids in het Noorden">
    <script type="application/ld+json">{"@type": "ChildrensEvent", "name": "Mega Indoor Springkussen Festival",
      "description": "Springen op meer dan veertig springkussens"}</script></head></html>"""
    facts = page_facts(html, "Mega Indoor Springkussen Festival")
    assert facts == {"type": "ChildrensEvent", "hints": {"soort": "kinderen", "woord": "springkussen"}}
    assert "veertig" not in json.dumps(facts)  # alleen de conclusie, geen tekst
    festival = page_facts('<html><meta property="og:description" content="Festival met drie podia en een line-up vol bands"></html>')
    assert festival["hints"]["podia"] in {"podia", "line-up"}


def test_fabriek_gebruikt_de_pagina_en_maakt_een_twijfellijst(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    rows = [
        {"id": "a", "title": "Mega Indoor Springkussen Festival", "startDate": "2026-11-01", "city": "Groningen",
         "verificationStatus": "organizer_confirmed", "eventUrl": "https://spring.example/a", "sourceUrl": "https://spring.example/a"},
        {"id": "b", "title": "Wende", "startDate": "2026-11-02", "city": "Groningen",
         "verificationStatus": "organizer_confirmed", "eventUrl": "https://podium.example/b", "sourceUrl": "https://podium.example/b"},
        {"id": "c", "title": "Dorpsfestival Ten Boer", "startDate": "2026-11-03", "city": "Ten Boer",
         "verificationStatus": "organizer_confirmed", "eventUrl": "https://dorp.example/c", "sourceUrl": "https://dorp.example/c"},
    ]
    (data / "events.json").write_text(json.dumps(rows))
    cache = {"pages": {"https://podium.example/b": {"type": "TheaterEvent"}}}
    events, status = build(data, out, date(2026, 10, 12), {}, photo_cache=cache)
    by_id = {e["id"]: e for e in events}
    assert by_id["a"]["kind"] == "kinderen"
    assert by_id["b"]["kind"] == "theater" and by_id["b"]["classification"]["method"] == "organisator"
    assert "schemaType" not in by_id["b"] and "pageHints" not in by_id["b"]
    doubts = {d["id"]: d for d in status["_twijfel"]}
    assert set(doubts) == {"c"} and status["twijfel"] == 1
    assert any("festival" in why for why in doubts["c"]["waarom"])


def test_vuistregel_blijft_op_de_twijfellijst(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    (data / "events.json").write_text(json.dumps([{"id": "l", "title": "Stadslichtfestival Hoogeveen", "startDate": "2026-12-11",
        "city": "Hoogeveen", "verificationStatus": "organizer_confirmed", "eventUrl": "https://l.example/", "sourceUrl": "https://l.example/"}]))
    overrides = {"namen": [{"naam": "lichtfestival", "soort": "kunst", "reden": "lichtkunst", "nakijken": True}]}
    events, status = build(data, out, date(2026, 10, 12), overrides, photo_cache={})
    assert events[0]["kind"] == "kunst" and events[0]["classification"]["nakijken"] is True
    assert status["twijfel"] == 1


def test_kerkdienst_is_geen_uitje_een_kerkconcert_wel(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    rows = [{"id": i, "title": t, "startDate": "2026-11-01", "city": "Beilen", "verificationStatus": "organizer_confirmed",
             "eventUrl": f"https://kerk.example/{i}", "sourceUrl": f"https://kerk.example/{i}"}
            for i, t in (("a", "Eredienst WG Beilen"), ("b", "Orgelconcert in de Pauluskerk"), ("c", "Kerkdienst met ds. Jansen"))]
    (data / "events.json").write_text(json.dumps(rows))
    events, status = build(data, out, date(2026, 10, 12), {}, photo_cache={})
    assert [e["title"] for e in events] == ["Orgelconcert in de Pauluskerk"]
    assert status["geenUitje"] == 2


def test_datum_voor_de_titel_gaat_eraf():
    from pipeline.v2.convert import clean_title
    assert clean_title("7 februari 2027 om 14.30 uur – Amsterdams-Berlijns trio Jolly Mangos") == "Amsterdams-Berlijns trio Jolly Mangos"
    assert clean_title("Zondag 15 november 2026 – 14.30 uur – Florence Foster Jenkins") == "Florence Foster Jenkins"
    assert clean_title("1 mei Optocht") == "1 mei Optocht"  # geen scheidingsteken: de datum hoort bij de naam
    assert clean_title("  Wende  ") == "Wende"
