"""Dorpswebsites zoeken: heeft elke plaats in het werkgebied een eigen website?

Veel dorpen hebben een eigen website (van dorpsbelangen, het dorpshuis of een dorpsvereniging),
vaak met een agenda. Die staat zelden in OpenStreetMap of Wikidata. Daarom kijkt de motor per plaats:

1. Welke plaatsen liggen in het werkgebied? Wikidata: dorpen, gehuchten en steden, met gemeente,
   provincie en postcode.
2. Welke websitenamen gebruiken dorpen vaak? eenrum.nl, dorpsbelangeneenrum.nl, eenrum-online.nl,
   enzovoort. Alleen een naam die echt bestaat (DNS) wordt bekeken: eerst robots.txt, dan de voorpagina.
3. Is het echt de website van dit dorp? De plaatsnaam moet erop staan, de site mag niet 'te koop' of
   leeg zijn en moet bij deze plek horen (de gemeente, een postcode uit de buurt of dorpen in de buurt
   staan op de pagina). Met duidelijke dorpswoorden (dorpsbelangen, dorpshuis, plaatselijk belang, ...)
   is het een dorpssite; zonder is het twijfel en wordt de site niet vanzelf gebruikt.
4. Dorpssites gaan naar de bronwachtrij (collector/discover_venues.py). Daarna test de probe of er een
   agenda is die de robot kan lezen.

Resultaat: data/dorpssites.json, per plaats wanneer er gekeken is en wat er gevonden is. Elke plaats
komt na RECHECK_DAYS opnieuw aan de beurt. Werkt voor elk werkgebied (AREA_CENTER en AREA_RADIUS_KM),
dus ook als UITNU landelijk wordt.

Draaien:  python -m collector.village_sites --store data/dorpssites.json --budget-minutes 10 --summary
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from datetime import date
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
from typing import Callable
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlparse

from collector.discover_venues import (AREA_CENTER, AREA_RADIUS_KM, WIKIDATA_URL, _fetch_json, distance_km,
                                       is_excluded, normalize_website)
from collector.site_crawler import USER_AGENT, Fetched, default_fetch
from collector.source_candidates import canonical_url, host_key
from collector.source_probe import _robots_for, soft_redirect

STORE_PATH = "data/dorpssites.json"
RECHECK_DAYS = 90        # na zoveel dagen een plaats opnieuw nalopen
RETRY_DAYS = 14          # een website die niet bereikbaar was eerder opnieuw proberen
NEARBY_KM = 10           # dorpen binnen deze afstand tellen als 'in de buurt'

# Wikidata: soorten plaatsen. Dorp, stadje, stad, woonplaats (NL); gehucht, nederzetting; grote stad.
VILLAGE_TYPES = {"Q532", "Q3957", "Q515", "Q1852859"}
HAMLET_TYPES = {"Q5084", "Q486972"}
BIG_CITY = "Q1549591"   # een grote stad heeft geen dorpswebsite: alleen de officiële website bekijken

# Alle plaatsen van het land in één keer (gewone SPARQL, zodat ook een reserve-adres werkt). Het werkgebied
# wordt daarna uitgeknipt; de rest van het land is nodig om te weten welke plaatsnamen vaker voorkomen.
PLACES_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?item ?label ?fy ?coord ?type ?website ?postcode ?gemeenteLabel ?provincieLabel WHERE {{
  ?item wdt:P17 wd:{country} ; wdt:P31 ?type ; wdt:P625 ?coord .
  VALUES ?type {{ {types} }}
  ?item rdfs:label ?label . FILTER(LANG(?label) = "nl")
  OPTIONAL {{ ?item rdfs:label ?fy . FILTER(LANG(?fy) = "fy") }}
  OPTIONAL {{ ?item wdt:P856 ?website . }}
  OPTIONAL {{ ?item wdt:P281 ?postcode . }}
  OPTIONAL {{ ?item wdt:P131 ?gemeente . ?gemeente wdt:P31 wd:Q2039348 ; rdfs:label ?gemeenteLabel .
             FILTER(LANG(?gemeenteLabel) = "nl")
             OPTIONAL {{ ?gemeente wdt:P131 ?provincie . ?provincie wdt:P31 wd:Q134390 ; rdfs:label ?provincieLabel .
                        FILTER(LANG(?provincieLabel) = "nl") }} }}
}}
"""
# Wikidata zelf, en anders een snelle kopie van Wikidata (QLever, Universiteit van Freiburg).
SPARQL_ENDPOINTS = (WIKIDATA_URL, "https://qlever.dev/api/wikidata")

# Websitenamen die dorpen veel gebruiken. {s} = eenrum, {h} = nieuw-beerta, {p} = provincie.
CORE_PATTERNS = (
    "{s}.nl", "{h}.nl", "{s}.com", "{s}.info", "{s}.net", "{s}.org", "dorp{s}.nl", "dorpsbelang{s}.nl",
    "dorpsbelangen{s}.nl", "plaatselijkbelang{s}.nl", "{s}online.nl", "dorpshuis{s}.nl",
)
VILLAGE_PATTERNS = (
    "{s}.nu", "{s}.eu", "{s}.frl", "{h}.com", "{h}.info", "{s}-online.nl", "{s}info.nl", "{s}-info.nl",
    "dorpsbelangen-{h}.nl", "dorpsbelang-{h}.nl", "plaatselijk-belang-{h}.nl", "pb{s}.nl",
    "dorpsvereniging{s}.nl", "vereniging{s}.nl", "doarpsbelang{s}.nl", "dorpshuis-{h}.nl", "mfc{s}.nl",
    "ons{s}.nl", "mijn{s}.nl", "in{s}.nl", "{s}actueel.nl", "{s}leeft.nl", "{s}bruist.nl", "beleef{s}.nl",
    "{s}-{p}.nl", "{s}{p}.nl",
)

PROVINCE_NAMES = {"friesland": ("friesland", "fryslan"), "fryslan": ("friesland", "fryslan")}

# Woorden die bijna alleen op de website van een dorp (of het dorpshuis) staan.
VILLAGE_WORDS = re.compile(
    r" (?:vereniging )?dorpsbelang(?:en)? | plaatselijk belang | dorpsvereniging | dorpshuis | dorpscentrum "
    r"| buurthuis | wijkcentrum | multifunctioneel centrum | mfc | kulturhus | dorpsraad | wijkraad "
    r"| buurtvereniging | dorpskrant | dorpsblad | dorpsagenda | dorpsfeest | ons dorp | us doarp "
    r"| doarpsbelang | doarpshus | doarpshuis | it doarp | mienskip | feestvereniging | oranjevereniging "
    r"| oranjecomite | ijsvereniging | dorpsplein | dorpsbewoners | dorpsgenoten | dorpsgemeenschap "
    r"| dorpsleven ")
# Een websitenaam als dorpsbelangeneenrum.nl of mfcengelbert.nl zegt zelf al dat het om het dorp gaat.
VILLAGE_HOST = re.compile(r"dorpsbelang|doarpsbelang|plaatselijkbelang|plaatselijk-belang|dorpsvereniging|dorpshuis"
                          r"|^(?:www\.)?(?:mfc|pb)")
# Woorden van een bedrijf of webwinkel: dan is het (waarschijnlijk) geen dorpssite.
BUSINESS_WORDS = re.compile(
    r" (?:winkelwagen|winkelmand|webshop|offerte|bestellen|prijslijst|b v|v o f|kamer boeken|boek nu"
    r"|reserveer nu|onze diensten|vacatures|aanbiedingen|gratis verzending|afrekenen) ")
# Een domeinnaam die te koop staat, geparkeerd is of nog leeg ('binnenkort online').
PARKED_STRONG = re.compile(
    r" (?:domein(?:naam)?|domain(?: name)?) (?:\w+ ){0,6}(?:te koop|for sale|kopen|buy|geparkeerd|parked"
    r"|gereserveerd|reserved|geregistreerd|registered) | sedo | sedoparking | dan com | afternic "
    r"| hugedomains | parkingcrew | bodis | this domain | deze domeinnaam ")
PARKED_WEAK = re.compile(
    r" (?:coming soon|binnenkort online|binnenkort beschikbaar|under construction|in aanbouw|wordt aan gewerkt"
    r"|welcome to nginx|it works|index of|default (?:web )?page|account (?:has been )?suspended"
    r"|website is (?:tijdelijk )?offline|plesk|cpanel|directadmin|hostnet|transip|mijndomein|strato|vimexx"
    r"|antagonist|versio|one com|hostinger|godaddy) ")
POSTCODE = re.compile(r"\b([1-9]\d{3})\s?[A-Z]{2}\b")


def plain(text: str) -> str:
    """'’t Zandt (Gr.)' -> ' t zandt gr ': kleine letters, geen accenten, alleen letters en cijfers."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " " + " ".join(re.findall(r"[a-z0-9]+", text)) + " "


def clean_name(label: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", str(label or "")).strip()


def slugs(name: str) -> tuple[str, str]:
    """('nieuwbeerta', 'nieuw-beerta') voor 'Nieuw-Beerta'; ('tzandt', 't-zandt') voor "'t Zandt"."""
    words = plain(clean_name(name).replace("'", "").replace("’", "")).split()
    return "".join(words), "-".join(words)


def domain_guesses(place: dict) -> list[str]:
    """Websitenamen om te proberen, de meest gebruikte eerst. Gehuchten krijgen alleen de gewone namen."""
    if place.get("soort") == "stad":
        return []
    patterns = CORE_PATTERNS + (VILLAGE_PATTERNS if place.get("soort") == "dorp" else ())
    provinces = [plain(p).strip().replace(" ", "") for p in place.get("provincies") or []][:1]
    found: list[str] = []
    for name in place.get("namen") or [place.get("naam", "")]:
        s, h = slugs(name)
        if len(s) < 3:
            continue
        for pattern in patterns:
            for province in (provinces if "{p}" in pattern else [""]):
                domain = pattern.format(s=s, h=h, p=province)
                if domain not in found:
                    found.append(domain)
    return found


# --- plaatsen uit Wikidata ---------------------------------------------------------------------------

def places_query(country: str = "Q55") -> str:
    types = " ".join(f"wd:{q}" for q in sorted(VILLAGE_TYPES | HAMLET_TYPES | {BIG_CITY}))
    return PLACES_QUERY.format(country=country, types=types)


def fetch_places(country: str = "Q55", endpoints: tuple[str, ...] = SPARQL_ENDPOINTS) -> dict:
    """Alle plaatsen van het land. Lukt het bij Wikidata niet (druk of storing), dan bij de kopie."""
    body = urlencode({"query": places_query(country), "format": "json"}).encode("utf-8")
    problems = []
    for endpoint in endpoints:
        try:
            return _fetch_json(endpoint, data=body, timeout=180)
        except Exception as error:
            problems.append(f"{endpoint}: {error}")
    raise RuntimeError("; ".join(problems))


def shared_names(payload: dict, km: float = 15) -> list[str]:
    """Plaatsnamen die in het land vaker voorkomen, op plekken verder dan km uit elkaar.
    Bij zo'n naam moet de website laten zien dat hij bij déze plek hoort."""
    points: dict[str, list[tuple[float, float]]] = {}
    for row in payload.get("results", {}).get("bindings", []):
        match = re.match(r"Point\(([-0-9.]+) ([-0-9.]+)\)", row.get("coord", {}).get("value", ""), re.I)
        name = plain(clean_name((row.get("label") or row.get("itemLabel") or {}).get("value", ""))).strip()
        point = (float(match.group(2)), float(match.group(1))) if match else None
        if point and name and point not in points.get(name, []):
            points.setdefault(name, []).append(point)
    return sorted(name for name, spots in points.items()
                  if any(distance_km(a[0], a[1], b) > km for i, a in enumerate(spots) for b in spots[i + 1:]))


def places_from_wikidata(payload: dict, *, center: tuple[float, float] = AREA_CENTER,
                         radius_km: float | None = AREA_RADIUS_KM) -> list[dict]:
    """Eén regel per plaats in het werkgebied, met alle namen, websites en postcodes bij elkaar."""
    places: dict[str, dict] = {}
    for row in payload.get("results", {}).get("bindings", []):
        qid = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        label = clean_name((row.get("label") or row.get("itemLabel") or {}).get("value", ""))
        match = re.match(r"Point\(([-0-9.]+) ([-0-9.]+)\)", row.get("coord", {}).get("value", ""), re.I)
        if not qid or not label or re.fullmatch(r"Q\d+", label) or not match:
            continue
        lat, lon = float(match.group(2)), float(match.group(1))
        if qid not in places and radius_km is not None and distance_km(lat, lon, center) > radius_km:
            continue
        place = places.setdefault(qid, {
            "qid": qid, "naam": label, "namen": [label], "soort": "gehucht",
            "lat": round(lat, 5), "lon": round(lon, 5),
            "gemeenten": [], "provincies": [], "postcodes": [], "websites": [],
        })
        kind = row.get("type", {}).get("value", "").rsplit("/", 1)[-1]
        if kind == BIG_CITY:
            place["soort"] = "stad"
        elif kind in VILLAGE_TYPES and place["soort"] != "stad":
            place["soort"] = "dorp"
        frisian = clean_name(row.get("fy", {}).get("value", ""))
        if frisian and plain(frisian) not in {plain(n) for n in place["namen"]}:
            place["namen"].append(frisian)
        website = normalize_website(row.get("website", {}).get("value"))
        if website and website not in place["websites"]:
            place["websites"].append(website)
        for code in re.findall(r"\b[1-9]\d{3}\b", row.get("postcode", {}).get("value", "")):
            if code not in place["postcodes"]:
                place["postcodes"].append(code)
        # Ook vroegere gemeenten (Loppersum, Bierum): die namen gebruiken dorpen vaak nog.
        for key, field in (("gemeenten", "gemeenteLabel"), ("provincies", "provincieLabel")):
            value = row.get(field, {}).get("value", "")
            if value and value not in place[key] and not re.fullmatch(r"Q\d+", value):
                place[key].append(value)
    return sorted(places.values(), key=lambda p: (p["soort"] != "dorp", p["naam"]))


def nearby_names(places: list[dict], km: float = NEARBY_KM) -> dict[str, list[str]]:
    """Per plaats de namen van dorpen in de buurt (die staan vaak op een dorpswebsite)."""
    villages = [p for p in places if p.get("soort") == "dorp" and len(plain(p["naam"]).strip()) >= 5]
    out: dict[str, list[str]] = {}
    for place in places:
        own = plain(place["naam"])
        out[place["qid"]] = sorted({
            plain(other["naam"]) for other in villages
            if other["qid"] != place["qid"] and plain(other["naam"]) != own
            and abs(other["lat"] - place["lat"]) < 0.2 and abs(other["lon"] - place["lon"]) < 0.3
            and distance_km(other["lat"], other["lon"], (place["lat"], place["lon"])) <= km
        })
    return out


# --- een website beoordelen ----------------------------------------------------------------------------

class _PageText(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.parts, self._skip, self._in_title = "", [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            values = {str(k).lower(): str(v or "") for k, v in attrs}
            if values.get("name", values.get("property", "")).lower() in {"description", "og:site_name", "og:title"}:
                self.parts.append(values.get("content", ""))

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def page_text(html: str) -> tuple[str, str]:
    parser = _PageText()
    try:
        parser.feed(html[:400_000])
    except Exception:
        pass
    return " ".join(parser.title.split()), " ".join(" ".join(parser.parts).split())[:60_000]


def region_score(place: dict, text: str, nearby: list[str]) -> tuple[int, list[str]]:
    """Hoort de pagina bij deze plek? Punten voor gemeente, postcode, dorpen in de buurt en provincie."""
    flat = plain(text)
    score, why = 0, []
    for gemeente in place.get("gemeenten") or []:
        if plain(gemeente) != plain(place["naam"]) and plain(gemeente) in flat:
            score, why = score + 2, why + [f"gemeente {gemeente}"]
            break
    codes = {int(c) for c in place.get("postcodes") or []}
    # Jaartallen ('2026 NK') lijken op een postcode: die tellen niet mee.
    on_page = {int(c) for c in POSTCODE.findall(text) if not 1900 <= int(c) <= 2099}
    if codes and on_page:
        if codes & on_page:
            score, why = score + 3, why + ["eigen postcode"]
        elif {c // 100 for c in codes} & {c // 100 for c in on_page}:
            score, why = score + 2, why + ["postcode uit de buurt"]
        else:
            score, why = score - 2, why + ["postcode van elders"]
    neighbours = [n for n in nearby if n in flat]
    if neighbours:
        score += 2 if len(neighbours) >= 2 else 1
        why.append("dorpen in de buurt (" + ", ".join(n.strip() for n in neighbours[:3]) + ")")
    for province in place.get("provincies") or []:
        key = plain(province).strip()
        if any(f" {name} " in flat for name in PROVINCE_NAMES.get(key, (key,))):
            score, why = score + 1, why + [f"provincie {province}"]
            break
    return score, why


def judge_page(place: dict, title: str, text: str, nearby: list[str], *, official: bool = False,
               host: str = "") -> tuple[str, str]:
    """Oordeel over een voorpagina: 'dorpssite', 'twijfel' of 'nee', met de reden in gewone taal.

    place['dubbeleNaam'] zegt of de plaatsnaam in het land vaker voorkomt; dan moet de pagina
    laten zien dat hij bij déze plek hoort (gemeente, postcode of dorpen in de buurt)."""
    flat = plain(f"{title} {text}")
    words = len(flat.split())
    if words < 25:
        return "nee", "(bijna) lege pagina"
    if (PARKED_STRONG.search(flat) and words < 600) or (PARKED_WEAK.search(flat) and words < 120):
        return "nee", "domeinnaam te koop, geparkeerd of nog leeg"
    names = [plain(n) for n in place.get("namen") or [place["naam"]]]
    if not any(name in flat for name in names):
        return "nee", "de plaatsnaam staat niet op de pagina"
    heading = plain(title)
    if " gemeente " in heading and not VILLAGE_WORDS.search(heading) and (not place.get("gemeenten") or any(
            f" gemeente {plain(g).strip()} " in heading for g in place["gemeenten"])):
        return "nee", "website van de gemeente (die zoekt de motor al apart)"
    score, why = region_score(place, f"{title} {text}", nearby)
    village = sorted({m.strip() for m in VILLAGE_WORDS.findall(flat)})
    business = sorted({m.strip() for m in BUSINESS_WORDS.findall(flat)})
    if host and VILLAGE_HOST.search(host):
        village.append(f"websitenaam {host}")
    if not village and not business and re.search(r" (?:ons |dit |het |kleine )?(?:dorp|doarp) ", flat):
        village.append("dorp")
    if official:
        if score < 0:
            return "twijfel", "officiële website volgens Wikidata, maar " + ", ".join(why)
        return "dorpssite", "officiële website volgens Wikidata"
    if score < 2 and village and score >= 0 and place.get("dubbeleNaam") is False:
        return "dorpssite", f"dorpswoorden ({', '.join(village[:3])}); de plaatsnaam komt in het land maar één keer voor"
    if score < 2:
        reason = ", ".join(why) if why else "niets op de pagina wijst naar deze streek"
        return ("twijfel" if village and score >= 0 else "nee"), f"hoort misschien bij een andere plaats: {reason}"
    if village:
        return "dorpssite", f"dorpswoorden ({', '.join(village[:3])}); {', '.join(why)}"
    if len(business) >= 2:
        return "nee", f"lijkt een bedrijf ({', '.join(business[:3])})"
    return "twijfel", f"hoort bij deze streek ({', '.join(why)}), maar geen dorpswoorden"


def site_name(title: str, place_name: str) -> str:
    """Een korte naam uit de paginatitel: 'Home - Dorpsbelangen Eenrum' -> 'Dorpsbelangen Eenrum'."""
    parts = [p.strip() for p in re.split(r"\s+[|\-–—:·»]\s+|\s*\|\s*", title or "") if p.strip()]
    parts = [p for p in parts if plain(p).strip() not in {"home", "welkom", "homepage", "startpagina", "index"}]
    own = [p for p in parts if plain(place_name) in plain(p)]
    name = (own or parts or [place_name])[0]
    return name[:80]


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _redirect(exc: HTTPError, base: str) -> str:
    """Het adres waar een doorverwijzing (die de crawler zelf niet volgt) naartoe wijst."""
    location = exc.headers.get("Location") if exc.code in (301, 302, 303, 307, 308) and exc.headers else None
    return canonical_url(urljoin(base, location)) if location else ""


def _own_host(host: str, place: dict) -> bool:
    """Draagt deze websitenaam de naam van de plaats? (dorpsbelangeneenrum.nl bij Eenrum)"""
    flat = host.replace("-", "").replace(".", "")
    return any(slugs(name)[0] in flat for name in place.get("namen") or [place["naam"]] if len(slugs(name)[0]) >= 3)


def check_site(url: str, place: dict, nearby: list[str], *, fetcher: Callable[..., Fetched] = default_fetch,
               timeout: float = 12, official: bool = False) -> dict:
    """Bekijk één website, met respect voor robots.txt.

    Verhuist de site naar een websitenaam met de plaatsnaam erin, dan volgt hij die; een doorverwijzing
    naar een heel andere website (een domeinhandel, de gemeente) telt niet als dorpswebsite."""
    origin = _origin(canonical_url(url))
    result = {"url": origin + "/", "adres": url}
    tried_http = False

    def moved(target: str) -> dict | None:
        nonlocal origin
        new = _origin(target)
        if host_key(new) != host_key(origin) and not (official or _own_host(host_key(new), place)):
            return {**result, "oordeel": "nee", "reden": f"verwijst door naar {host_key(new)}"}
        origin = new
        result["url"] = origin + "/"
        return None

    for _ in range(4):
        # 1. Verhuisd? Een doorverwijzing van robots.txt naar een andere website zegt waar de site nu staat.
        try:
            fetcher(origin + "/robots.txt", timeout=timeout)
        except HTTPError as exc:
            target = _redirect(exc, origin + "/robots.txt")
            if target and _origin(target) != origin:
                if (stop := moved(target)) is not None:
                    return stop
                continue
        except Exception as exc:
            if origin.startswith("https://") and not tried_http:
                tried_http, origin = True, "http://" + origin[len("https://"):]  # alleen via http (oud certificaat)
                result["url"] = origin + "/"
                continue
            return {**result, "oordeel": "fout", "reden": f"niet bereikbaar ({type(exc).__name__})"}
        if is_excluded(origin):
            return {**result, "oordeel": "nee", "reden": f"verwijst naar {host_key(origin)}"}
        # 2. robots.txt: mag de robot de voorpagina lezen?
        robots, status = _robots_for(origin + "/", fetcher, timeout)
        if status == "unavailable":
            return {**result, "oordeel": "fout", "reden": "robots.txt niet bereikbaar"}
        if not robots.can_fetch(USER_AGENT, origin + "/"):
            return {**result, "oordeel": "nee", "reden": "robots.txt staat de robot niet toe"}
        # 3. De voorpagina.
        try:
            page = fetcher(origin + "/", timeout=timeout)
        except HTTPError as exc:
            target = _redirect(exc, origin + "/")
            if target and _origin(target) != origin:
                if (stop := moved(target)) is not None:
                    return stop
                continue
            return {**result, "oordeel": "fout" if exc.code >= 500 else "nee", "reden": f"foutmelding {exc.code}"}
        except Exception as exc:
            return {**result, "oordeel": "fout", "reden": f"niet bereikbaar ({type(exc).__name__})"}
        html = page.text or ""
        target = soft_redirect(html, page.url or origin + "/")
        if target and robots.can_fetch(USER_AGENT, target):
            try:
                page = fetcher(target, timeout=timeout)
                html = page.text or ""
            except Exception as exc:
                return {**result, "oordeel": "fout", "reden": f"niet bereikbaar ({type(exc).__name__})"}
        if page.url:
            result["url"] = canonical_url(page.url) or result["url"]
        title, text = page_text(html)
        verdict, reason = judge_page(place, title, text, nearby, official=official, host=host_key(result["url"]))
        result.update(oordeel=verdict, reden=reason, titel=title[:120], naam=site_name(title, place["naam"]))
        return result
    return {**result, "oordeel": "nee", "reden": "te veel doorverwijzingen"}


# --- bestaat een websitenaam? ---------------------------------------------------------------------------

def system_resolver(host: str) -> bool:
    try:
        return bool(socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP))
    except (OSError, UnicodeError):
        return False


class DohResolver:
    """DNS via HTTPS (dns.google), voor omgevingen zonder gewone DNS. Onthoudt namen die niet bestaan,
    zodat 'www.' + zo'n naam niet nog eens gevraagd wordt."""

    def __init__(self, fetch_json: Callable[..., dict] = _fetch_json):
        self.fetch_json, self.missing, self.lock = fetch_json, set(), threading.Lock()

    def __call__(self, host: str) -> bool:
        parent = host[4:] if host.startswith("www.") else None
        if parent and parent in self.missing:
            return False
        for attempt in range(3):
            try:
                data = self.fetch_json("https://dns.google/resolve?" + urlencode({"name": host, "type": "A"}),
                                       timeout=15)
                break
            except Exception:
                time.sleep(1 + attempt)
        else:
            return False
        if data.get("Status") == 3:
            with self.lock:
                self.missing.add(host)
            return False
        return data.get("Status") == 0 and any(a.get("type") in (1, 5) for a in data.get("Answer") or [])


def existing_host(domain: str, resolver: Callable[[str], bool]) -> str | None:
    """'eenrum.nl' of 'www.eenrum.nl' als die bestaat (sommige sites hebben alleen www)."""
    for host in (domain, "www." + domain):
        if resolver(host):
            return host
    return None


# --- per plaats ----------------------------------------------------------------------------------------

def check_place(place: dict, nearby: list[str], *, resolver: Callable[[str], bool] = system_resolver,
                fetcher: Callable[..., Fetched] = default_fetch, timeout: float = 12,
                shared: set[str] | frozenset[str] = frozenset()) -> list[dict]:
    """Alle websites van één plaats: de officiële (Wikidata) en de websitenamen die bestaan.

    Een 'officiële website' die bij meerdere plaatsen staat (meestal die van de gemeente) is niet
    de eigen website van het dorp en wordt overgeslagen."""
    tries: list[tuple[str, bool]] = [(url, True) for url in place.get("websites") or [] if host_key(url) not in shared]
    for domain in domain_guesses(place):
        host = existing_host(domain, resolver)
        if host:
            tries.append((f"https://{host}/", False))
    sites: list[dict] = []
    seen: set[str] = set()
    for url, official in tries:
        if is_excluded(url) or host_key(url) in seen:
            continue
        seen.add(host_key(url))
        site = check_site(url, place, nearby, fetcher=fetcher, timeout=timeout, official=official)
        final = host_key(site.get("url") or url)
        if final != host_key(url) and final in seen:
            continue  # zelfde website onder een andere naam
        seen.add(final)
        if official:
            site["bron"] = "wikidata"
        sites.append(site)
    return sites


def place_due(entry: dict | None, today: date) -> bool:
    if not entry or not entry.get("gekekenOp"):
        return True
    try:
        age = (today - date.fromisoformat(entry["gekekenOp"])).days
    except ValueError:
        return True
    if any(site.get("oordeel") == "fout" for site in entry.get("sites") or []):
        return age >= RETRY_DAYS
    return age >= RECHECK_DAYS


def load_store(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"version": 1, "plaatsen": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("plaatsen", {})
    return payload


def save_store(path: str | Path, store: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run(places: list[dict], store: dict, *, resolver: Callable[[str], bool] = system_resolver,
        fetcher: Callable[..., Fetched] = default_fetch, workers: int = 12, timeout: float = 12,
        today: str | None = None, budget_seconds: float | None = None, limit: int | None = None) -> dict:
    """Loop de plaatsen na die aan de beurt zijn (nog nooit gekeken eerst) en werk de opslag bij.

    store['dubbeleNamen'] (als die er is): plaatsnamen die in het land vaker voorkomen."""
    day = date.fromisoformat(today) if today else date.today()
    known = store.setdefault("plaatsen", {})
    if store.get("dubbeleNamen") is not None:
        shared_set = set(store["dubbeleNamen"])
        for place in places:
            place["dubbeleNaam"] = any(plain(n).strip() in shared_set for n in place.get("namen") or [place["naam"]])
    due = [p for p in places if place_due(known.get(p["qid"]), day)]
    due.sort(key=lambda p: (bool((known.get(p["qid"]) or {}).get("gekekenOp")),
                            (known.get(p["qid"]) or {}).get("gekekenOp") or "",
                            p.get("soort") != "dorp", distance_km(p["lat"], p["lon"])))
    waiting = len(due)
    if limit is not None:
        due = due[:max(0, limit)]
    near = nearby_names(places)
    hosts = Counter(host_key(url) for p in places for url in set(p.get("websites") or []))
    shared = frozenset(host for host, count in hosts.items() if count > 1)
    done = 0
    if due:
        pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(due))))
        futures = {pool.submit(check_place, p, near.get(p["qid"], []), resolver=resolver, fetcher=fetcher,
                               timeout=timeout, shared=shared): p for p in due}
        try:
            for future in as_completed(futures, timeout=budget_seconds):
                place = futures[future]
                try:
                    sites = future.result()
                except Exception as exc:  # één plaats die misgaat, mag de rest niet tegenhouden
                    sites = [{"url": "", "oordeel": "fout", "reden": f"{type(exc).__name__}: {exc}"[:200]}]
                known[place["qid"]] = {
                    "naam": place["naam"], "soort": place["soort"], "gemeente": (place.get("gemeenten") or [""])[0],
                    "lat": place["lat"], "lon": place["lon"], "gekekenOp": day.isoformat(), "sites": sites,
                }
                done += 1
        except FuturesTimeout:
            pass  # tijd op: de rest komt de volgende keer als eerste
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    store["bijgewerkt"] = day.isoformat()
    return {"plaatsen": len(places), "aanDeBeurt": waiting, "nagelopen": done, **summary(store)}


def summary(store: dict) -> dict:
    counts = {"dorpssite": 0, "twijfel": 0, "nee": 0, "fout": 0}
    with_site = 0
    for entry in (store.get("plaatsen") or {}).values():
        verdicts = [site.get("oordeel") for site in entry.get("sites") or []]
        for verdict in verdicts:
            if verdict in counts:
                counts[verdict] += 1
        with_site += "dorpssite" in verdicts
    return {"plaatsenMetDorpssite": with_site, "websites": counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UITNU: per plaats de eigen dorpswebsite zoeken")
    parser.add_argument("--store", default=STORE_PATH)
    parser.add_argument("--radius-km", type=int, default=AREA_RADIUS_KM)
    parser.add_argument("--places-json", help="eerder opgeslagen Wikidata-antwoord met plaatsen (voor testen)")
    parser.add_argument("--budget-minutes", type=float, default=None, help="stop na zoveel minuten")
    parser.add_argument("--limit", type=int, default=None, help="hoogstens zoveel plaatsen per keer")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--doh", action="store_true", help="DNS via HTTPS (als gewone DNS niet werkt)")
    parser.add_argument("--summary", action="store_true", help="kort verslag tonen")
    args = parser.parse_args(argv)

    store = load_store(args.store)
    day = date.today().isoformat()
    if store.get("klaarOp") == day and not args.places_json:
        print("Vandaag zijn alle plaatsen die aan de beurt waren al nagelopen.")
        return 0
    try:
        payload = (json.loads(Path(args.places_json).read_text(encoding="utf-8")) if args.places_json
                   else fetch_places())
    except Exception as error:  # Wikidata even niet bereikbaar: volgende keer verder
        print(f"Let op, lijst met plaatsen niet gelukt: {error}")
        return 0
    places = places_from_wikidata(payload, radius_km=args.radius_km)
    store["dubbeleNamen"] = shared_names(payload)
    report = run(places, store, resolver=DohResolver() if args.doh else system_resolver, workers=args.workers,
                 budget_seconds=args.budget_minutes * 60 if args.budget_minutes else None, limit=args.limit)
    if report["nagelopen"] >= report["aanDeBeurt"]:
        store["klaarOp"] = day
    save_store(args.store, store)
    if args.summary:
        print(f"Plaatsen in het werkgebied: {report['plaatsen']}; nagelopen: {report['nagelopen']} "
              f"(aan de beurt: {report['aanDeBeurt']})")
        print(f"Plaatsen met een eigen dorpswebsite: {report['plaatsenMetDorpssite']}; "
              f"websites: {json.dumps(report['websites'], ensure_ascii=False)}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
