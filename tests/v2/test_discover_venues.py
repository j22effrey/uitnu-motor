import json

from collector.discover_venues import (
    discoveries_from_overpass, discoveries_from_wikidata, is_excluded, main, normalize_website, overpass_query,
)

OSM = {"elements": [
    {"type": "node", "id": 1, "tags": {"amenity": "theatre", "name": "Theater De Klinker", "website": "www.deklinker.nl", "addr:city": "Winschoten"}},
    {"type": "way", "id": 2, "tags": {"amenity": "community_centre", "name": "Dorpshuis", "contact:website": "https://dorpshuis.example/agenda"}},
    {"type": "node", "id": 3, "tags": {"tourism": "museum", "name": "Museum", "website": "https://www.facebook.com/museum"}},
    {"type": "node", "id": 4, "tags": {"amenity": "cinema", "name": "Zonder site"}},
]}
WIKI = {"results": {"bindings": [
    {"item": {"value": "http://www.wikidata.org/entity/Q100"}, "itemLabel": {"value": "Testfestival"}, "website": {"value": "https://testfestival.example"}},
    {"item": {"value": "http://www.wikidata.org/entity/Q101"}, "itemLabel": {"value": "Agenda"}, "website": {"value": "https://www.visitgroningen.nl/x"}},
]}}


def test_website_netjes_maken():
    assert normalize_website("www.dorpshuis.nl") == "https://www.dorpshuis.nl/"
    assert normalize_website("") is None
    assert normalize_website("geen website") is None


def test_verzamelsites_en_sociale_media_overgeslagen():
    assert is_excluded("https://www.visitgroningen.nl/agenda")
    assert is_excluded("https://m.facebook.com/x")
    assert not is_excluded("https://www.deklinker.nl/")


def test_overpass_query_zoekt_in_het_werkgebied():
    query = overpass_query(60)
    assert "around:60000,53.2194,6.5665" in query
    assert '"amenity"="theatre"' in query and '"contact:website"' in query


def test_plekken_uit_openstreetmap():
    found = discoveries_from_overpass(OSM)
    assert [f["url"] for f in found] == ["https://www.deklinker.nl/", "https://dorpshuis.example/agenda"]
    assert found[0]["score"] > found[1]["score"]
    assert found[0]["from_url"] == "https://www.openstreetmap.org/node/1"


def test_festivals_uit_wikidata():
    found = discoveries_from_wikidata(WIKI)
    assert len(found) == 1 and found[0]["source_id"] == "wikidata:Q100"


def test_wachtrij_wordt_bijgewerkt(tmp_path):
    osm, wiki, queue, known = (tmp_path / n for n in ("osm.json", "wiki.json", "queue.json", "known.json"))
    osm.write_text(json.dumps(OSM)); wiki.write_text(json.dumps(WIKI))
    known.write_text(json.dumps({"sources": [{"rootUrl": "https://www.deklinker.nl/"}]}))
    assert main(["--queue", str(queue), "--known", str(known), "--osm-json", str(osm), "--wikidata-json", str(wiki)]) == 0
    hosts = {c["host"] for c in json.loads(queue.read_text())["candidates"]}
    assert hosts == {"dorpshuis.example", "testfestival.example"}
