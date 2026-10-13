"""Websites die verhuisd zijn of een kapot certificaat hebben: niet meer 'robots.txt niet bereikbaar'.
Op 13 oktober waren dat er 22 van de 101 (zoals dnk.nl -> denieuwekolk.nl en Theater De Winsinghhof)."""
import ssl
from datetime import date
from email.message import Message
from urllib.error import HTTPError, URLError

from collector.site_crawler import Fetched
from collector.source_probe import RETRY_DAYS, _apply_probe, probe_due, probe_source, robots_status

AGENDA = """<html><body><h1>Agenda</h1>
<ul><li><a href="/agenda/kerstconcert">Kerstconcert</a> za 19 december 2026 20:00</li>
<li><a href="/agenda/lezing">Lezing over de wierden</a> do 12 november 2026 19:30</li></ul></body></html>"""


def _moved(url, location):
    headers = Message()
    headers["Location"] = location
    return HTTPError(url, 301, "Moved Permanently", headers, None)


def test_verhuisde_website_krijgt_het_nieuwe_adres():
    def fetcher(url, timeout=15):
        raise _moved(url, "https://denieuwekolk.nl/robots.txt")

    _, status, moved_to = robots_status("https://dnk.nl/", fetcher, 5)
    assert (status, moved_to) == ("moved", "https://denieuwekolk.nl/")
    result = probe_source("https://dnk.nl/", fetcher=fetcher)
    assert result.probe_status == "moved" and result.details["movedTo"] == "https://denieuwekolk.nl/"
    assert result.error == "verhuisd naar denieuwekolk.nl"


def test_doorsturen_binnen_dezelfde_website_is_geen_verhuizing():
    def fetcher(url, timeout=15):
        raise _moved(url, "https://www.dnk.nl/robots.txt")

    assert robots_status("https://dnk.nl/", fetcher, 5)[1] == "unavailable"


def test_kapot_certificaat_dan_via_http():
    asked = []

    def fetcher(url, timeout=15):
        asked.append(url)
        if url.startswith("https://"):
            raise URLError(ssl.SSLCertVerificationError("certificate verify failed: Hostname mismatch"))
        if url.endswith("/robots.txt"):
            return Fetched(url, 404, "text/plain", "")
        return Fetched(url, 200, "text/html", AGENDA)

    result = probe_source("https://www.theaterdewinsinghhof.example/", fetcher=fetcher,
                          today=date(2026, 10, 13))
    assert result.url == "http://www.theaterdewinsinghhof.example/"
    # Via http gelezen (de voorpagina is bekeken), niet meer 'niet bereikbaar'.
    assert result.details.get("viaHttp") and result.probe_status != "error"
    assert "http://www.theaterdewinsinghhof.example/" in asked
    item = {"url": "https://www.theaterdewinsinghhof.example/"}
    _apply_probe(item, result, "2026-10-13")
    assert item["url"] == "http://www.theaterdewinsinghhof.example/"  # zo wordt hij ook aangezet


def test_andere_storing_blijft_storing_en_komt_morgen_terug():
    def fetcher(url, timeout=15):
        raise URLError(ConnectionResetError(104, "Connection reset by peer"))

    result = probe_source("https://www.lawei.example/", fetcher=fetcher)
    assert result.probe_status == "error" and result.error == "robots.txt niet bereikbaar"
    item = {"probeStatus": "error", "probedAt": "2026-10-12"}
    assert probe_due(item, date(2026, 10, 13))
    assert RETRY_DAYS["moved"] == 30
    assert not probe_due({"probeStatus": "moved", "probedAt": "2026-10-12"}, date(2026, 10, 13))
