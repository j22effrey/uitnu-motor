"""Websites zoeken voor belangrijke plekken die in OpenStreetMap géén website hebben.

De motor vindt plekken vooral via OpenStreetMap, maar alleen als daar een website bij staat. Dinopark &
Landgoed Tenaxx in Wedde staat er bijvoorbeeld wel in (als pretpark), zonder website: zo bleef de
sprookjestocht buiten beeld. Daarom kijkt de motor voor elke belangrijke plek zonder website (pretparken,
dierentuinen, musea, theaters, bioscopen, podia, evenementenlocaties en clubs):

1. Staat er een Wikidata-nummer bij met een officiële website? Dan die.
2. Anders: websitenamen die bij de naam passen ('Landgoed Tenaxx Dinopark' -> dinoparklandgoedtenaxx.nl,
   landgoedtenaxx.nl, tenaxx.nl, ...). Alleen namen die echt bestaan (DNS) worden bekeken: eerst robots.txt,
   dan de voorpagina.
3. Hoort de website echt bij deze plek? Het eigen woord uit de naam ('tenaxx') moet in de titel staan, en de
   plaats of de provincie op de pagina; een geparkeerde of lege site telt niet.

Resultaat: data/plekwebsites.json (per plek wat er gevonden is, met een reden). Gevonden websites gaan via
collector/discover_venues.py de wachtrij in, zodat de probe ze test en de dekkingscontrole ze meetelt.
Werkt voor elk werkgebied (pipeline/area.py), dus ook als UITNU landelijk wordt.

Draaien:  python -m collector.plek_websites --store data/plekwebsites.json --budget-minutes 10 --summary
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from itertools import permutations
import json
from pathlib import Path
import re
import time
import urllib.parse
from typing import Callable

from collector.discover_venues import (OVERPASS_URLS, SPARQL_ENDPOINTS, _fetch_json, _first_that_works,
                                       _overpass_answer, is_excluded)
from collector.site_crawler import Fetched, default_fetch
from collector.source_candidates import host_key
from collector.village_sites import (DohResolver, PARKED_STRONG, PARKED_WEAK, PROVINCE_NAMES, check_site, existing_host, page_text,
                                     plain, system_resolver)
from pipeline import area

STORE_PATH = "data/plekwebsites.json"
RECHECK_DAYS = 90

# Plekken die er zeker in horen als ze een agenda hebben (zelfde soorten als de dekkingscontrole).
TYPES: dict[tuple[str, str], str] = {
    ("tourism", "theme_park"): "pretpark",
    ("tourism", "zoo"): "dierentuin",
    ("tourism", "museum"): "museum",
    ("amenity", "theatre"): "theater",
    ("amenity", "cinema"): "bioscoop",
    ("amenity", "arts_centre"): "cultuurcentrum",
    ("amenity", "music_venue"): "podium",
    ("amenity", "events_venue"): "evenementenlocatie",
    ("amenity", "nightclub"): "club",
}
# Woorden die niets zeggen over welke plek het is: wel in de websitenaam, niet als bewijs.
GENERIC = {"museum", "musea", "park", "landgoed", "dinopark", "dierenpark", "dierentuin", "zoo", "theater", "theatre",
           "schouwburg", "bioscoop", "cinema", "filmhuis", "cultuurcentrum", "cultuurhuis", "podium", "zaal", "club",
           "centrum", "huis", "het", "de", "den", "der", "van", "en", "the", "of", "stichting", "vereniging", "recreatie",
           "attractiepark", "pretpark", "speelpark", "familiepark", "openluchtmuseum", "bezoekerscentrum", "kerk",
           "molen", "boerderij", "oude", "nieuwe", "groot", "grote", "klein", "kleine"}
STOP = {"het", "de", "den", "der", "van", "en", "the", "of", "t", "s", "op", "aan", "in", "bij"}
SUFFIXES = (".nl", ".com")


def overpass_query(provinces: tuple[str, ...] = area.AREA_PROVINCES) -> str:
    codes = "|".join(area.iso_codes(tuple(provinces)))
    values: dict[str, list[str]] = {}
    for key, value in TYPES:
        values.setdefault(key, []).append(value)
    lines = [f'  nwr["{key}"~"^({"|".join(names)})$"]["name"][!"website"][!"contact:website"](area.werkgebied);'
             for key, names in values.items()]
    return ("[out:json][timeout:180];\n"
            f'area["ISO3166-2"~"^({codes})$"]->.werkgebied;\n'
            "(\n" + "\n".join(lines) + "\n);\nout center tags;")


def fetch_overpass(provinces: tuple[str, ...] = area.AREA_PROVINCES) -> dict:
    body = urllib.parse.urlencode({"data": overpass_query(provinces)}).encode("utf-8")
    problems = []
    for url in OVERPASS_URLS:
        try:
            return _overpass_answer(_fetch_json(url, data=body, timeout=200))
        except Exception as error:
            problems.append(f"{urllib.parse.urlparse(url).hostname}: {error}")
    raise RuntimeError("; ".join(problems))


def places_from_overpass(payload: dict) -> list[dict]:
    places = []
    for element in payload.get("elements") or []:
        tags = element.get("tags") or {}
        kind = next((label for (key, value), label in TYPES.items() if tags.get(key) == value), None)
        name = (tags.get("name") or "").strip()
        center = element.get("center") or element
        if not kind or not name or center.get("lat") is None:
            continue
        places.append({
            "id": f"{element.get('type')}/{element.get('id')}", "naam": name, "soort": kind,
            "plaats": tags.get("addr:city") or tags.get("addr:place") or "", "lat": center["lat"], "lon": center["lon"],
            "wikidata": tags.get("wikidata") or "",
        })
    return places


def wikidata_websites(qids: list[str], endpoints: tuple[str, ...] = SPARQL_ENDPOINTS) -> dict[str, str]:
    """Officiële website (P856) per Wikidata-nummer."""
    qids = [q for q in qids if re.fullmatch(r"Q\d+", q or "")]
    if not qids:
        return {}
    query = ("PREFIX wd: <http://www.wikidata.org/entity/>\nPREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
             "SELECT ?item ?website WHERE { VALUES ?item { " + " ".join(f"wd:{q}" for q in qids) + " } ?item wdt:P856 ?website . }")
    body = urllib.parse.urlencode({"query": query, "format": "json"}).encode("utf-8")
    rows = _first_that_works(endpoints, body, timeout=120).get("results", {}).get("bindings", [])
    return {row["item"]["value"].rsplit("/", 1)[-1]: row["website"]["value"] for row in rows}


def words_of(name: str) -> list[str]:
    return [w for w in plain(re.sub(r"\([^)]*\)", " ", name.replace("&", " "))).split() if w not in STOP]


# Plaatsnamen (uit data/dorpssites.json, aangevuld bij het draaien) zeggen niet wélke plek het is: 'Theater Assen'
# mag nooit assen.com worden (de stadsmarketing, een uitagenda).
PLACE_NAMES: set[str] = set()


def load_place_names(path: str | Path = "data/dorpssites.json") -> set[str]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names = set()
    for place in (payload.get("plaatsen") or {}).values():
        for value in (place.get("naam"), place.get("gemeente")):
            names.update(plain(value or "").split())
    return {n for n in names if len(n) >= 3}


def own_words(name: str, town: str = "") -> list[str]:
    """De woorden die zeggen wélke plek het is ('tenaxx' in 'Landgoed Tenaxx Dinopark'); geen plaatsnamen."""
    places = PLACE_NAMES | set(plain(town).split())
    for province in area.AREA_PROVINCES:
        places |= set(plain(province).split()) | set(PROVINCE_NAMES.get(plain(province).strip(), ()))
    return [w for w in words_of(name) if w not in GENERIC and w not in places and len(w) >= 3 and not w.isdigit()]


def domain_guesses(name: str, limit: int = 16, town: str = "") -> list[str]:
    words = words_of(name)[:4]
    own = own_words(name, town)
    if not own:
        return []  # alleen algemene woorden ('Museum'): niet te raden
    stems: list[str] = []

    def add(parts):
        joined = "".join(parts)
        if 4 <= len(joined) <= 40 and joined not in stems:
            stems.append(joined)

    add(words)
    add(own)
    for size in (3, 2):
        for combo in permutations(words, size):
            if any(w in own for w in combo):
                add(combo)
    for word in own:
        if len(word) >= 5:
            add([word])
    out: list[str] = []
    for stem in stems:
        for suffix in SUFFIXES:
            out.append(stem + suffix)
    return out[:limit]


def judge(place: dict, title: str, text: str) -> tuple[str, str]:
    """'gevonden', 'twijfel' of 'nee', met de reden."""
    flat = plain(f"{title} {text}")
    words = len(flat.split())
    if words < 25:
        return "nee", "(bijna) lege pagina"
    if (PARKED_STRONG.search(flat) and words < 600) or (PARKED_WEAK.search(flat) and words < 120):
        return "nee", "domeinnaam te koop, geparkeerd of nog leeg"
    own = own_words(place["naam"], place.get("plaats") or "")
    heading = plain(title)
    if not own or not all(f" {w} " in flat for w in own):
        return "nee", "de naam van de plek staat niet op de pagina"
    town = plain(place.get("plaats") or "").strip()
    if town and heading.strip() in {town, f"welkom in {town}", f"gemeente {town}"}:
        return "nee", "de website van de plaats zelf, niet van deze plek"
    if not any(f" {w} " in heading for w in own):
        return "twijfel", "de naam staat op de pagina, maar niet in de titel"
    region = [town] if town else []
    for province in area.AREA_PROVINCES:
        key = plain(province).strip()
        region += list(PROVINCE_NAMES.get(key, (key,)))
    if not any(f" {r} " in flat for r in region if r):
        return "twijfel", "niets op de pagina wijst naar deze plaats of provincie"
    return "gevonden", "de naam van de plek staat in de titel, en de plaats of provincie op de pagina"


def check_place(place: dict, *, official: str | None = None, resolver: Callable[[str], bool] = system_resolver,
                fetcher: Callable[..., Fetched] = default_fetch, timeout: float = 12, deadline: float | None = None) -> dict:
    """Zoek en controleer de website van één plek. Respecteert robots.txt (via village_sites.check_site)."""
    tries = [official] if official else []
    for domain in domain_guesses(place["naam"], town=place.get("plaats") or ""):
        if deadline and time.monotonic() > deadline:
            break
        host = existing_host(domain, resolver)
        if host:
            tries.append(f"https://{host}/")
    seen: set[str] = set()
    best = {"oordeel": "nee", "reden": "geen bestaande websitenaam gevonden"}
    temporary = False
    for url in tries:
        if not url or is_excluded(url) or host_key(url) in seen:
            continue
        seen.add(host_key(url))
        site = check_site(url, {"naam": place["naam"], "namen": [place["naam"]]}, [], fetcher=fetcher, timeout=timeout,
                          official=True)  # 'official': doorverwijzen naar een andere naam mag; het oordeel doet judge()
        if site.get("oordeel") == "fout":
            temporary = True
            continue
        if not site.get("titel") and site.get("oordeel") == "nee":
            continue
        try:
            page = fetcher(site["url"], timeout=timeout)
            title, text = page_text(page.text or "")
        except Exception:
            continue
        verdict, reason = judge(place, title, text)
        if url == official and verdict != "nee":
            # Een pagina op een andere website (gemeente, stichting) is niet de eigen website: eerst nakijken.
            own_site = urllib.parse.urlparse(official).path.strip("/") == ""
            verdict, reason = (("gevonden", "officiële website volgens Wikidata") if own_site
                               else ("twijfel", "officiële website volgens Wikidata is een pagina op een andere website"))
        result = {"url": site["url"], "oordeel": verdict, "reden": reason, "titel": title[:120]}
        if verdict == "gevonden":
            return result
        if verdict == "twijfel":
            best = result
    if best["oordeel"] == "nee" and temporary:
        return {"oordeel": "fout", "reden": "een website was tijdelijk niet bereikbaar"}
    return best


def load_store(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"uitleg": __doc__.split("\n\n")[0], "plekken": {}}


def save_store(path: str | Path, store: dict) -> None:
    Path(path).write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


RETRY_DAYS = 7          # een tijdelijke fout eerder opnieuw proberen
SEARCH_DAYS = 7         # OpenStreetMap hooguit eens per week vragen


def due(entry: dict | None, today: date) -> bool:
    if not entry or not entry.get("bekeken"):
        return True
    try:
        age = (today - date.fromisoformat(entry["bekeken"])).days
    except ValueError:
        return True
    return age >= (RETRY_DAYS if entry.get("oordeel") == "fout" else RECHECK_DAYS)


def run(places: list[dict], store: dict, *, today: date, budget_seconds: float, workers: int = 8,
        resolver: Callable[[str], bool] = system_resolver, fetcher: Callable[..., Fetched] = default_fetch,
        websites: dict[str, str] | None = None) -> int:
    todo = [p for p in places if due(store["plekken"].get(p["id"]), today)]
    deadline = time.monotonic() + budget_seconds
    done = 0
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(check_place, place, official=(websites or {}).get(place.get("wikidata")),
                           resolver=resolver, fetcher=fetcher, deadline=deadline): place for place in todo}
    try:
        for future in as_completed(futures, timeout=max(1, budget_seconds + 60)):
            place = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - één plek mag de rest niet tegenhouden
                result = {"oordeel": "fout", "reden": f"{type(exc).__name__}"}
            store["plekken"][place["id"]] = {**{k: place.get(k) for k in ("naam", "soort", "plaats", "lat", "lon", "wikidata")},
                                             **result, "bekeken": today.isoformat()}
            done += 1
            if time.monotonic() > deadline:
                break
    except Exception:  # noqa: BLE001 - tijd op: wat af is, blijft bewaard
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return done


def summary(store: dict) -> dict:
    counts: dict[str, int] = {}
    for entry in store.get("plekken", {}).values():
        counts[entry.get("oordeel", "?")] = counts.get(entry.get("oordeel", "?"), 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Websites zoeken voor plekken zonder website in OpenStreetMap")
    parser.add_argument("--store", default=STORE_PATH)
    parser.add_argument("--budget-minutes", type=float, default=10)
    parser.add_argument("--osm-json", help="antwoord van OpenStreetMap uit een bestand (voor proeven)")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--doh", action="store_true", help="DNS via HTTPS (voor omgevingen zonder gewone DNS)")
    args = parser.parse_args(argv)
    store = load_store(args.store)
    store.setdefault("plekken", {})
    PLACE_NAMES.update(load_place_names())
    today = date.today()
    searched = store.get("gezocht")
    recent = bool(searched) and (today - date.fromisoformat(searched)).days < SEARCH_DAYS
    if recent and not args.osm_json:
        # OpenStreetMap is deze week al gevraagd: alleen plekken die opnieuw aan de beurt zijn (een storing).
        places = [{"id": key, **value} for key, value in store["plekken"].items() if due(value, today)]
        if not places:
            if args.summary:
                print(f"Plekken zonder website: niets te doen (stand: {summary(store)}).")
            return 0
    else:
        try:
            payload = json.loads(Path(args.osm_json).read_text(encoding="utf-8")) if args.osm_json else fetch_overpass()
        except Exception as error:  # de servers zijn vaak druk: de volgende ronde opnieuw
            print(f"Plekken zonder website: OpenStreetMap lukte niet ({error}); volgende keer opnieuw.")
            return 0
        places = places_from_overpass(payload)
        store["gezocht"] = today.isoformat()
    try:
        websites = wikidata_websites(sorted({p["wikidata"] for p in places if p.get("wikidata")}))
    except Exception:
        websites = {}
    done = run(places, store, today=today, budget_seconds=args.budget_minutes * 60, websites=websites,
               resolver=DohResolver() if args.doh else system_resolver)
    save_store(args.store, store)
    if args.summary:
        print(f"Plekken zonder website in OpenStreetMap: {len(places)}; nu bekeken: {done}; stand: {summary(store)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
