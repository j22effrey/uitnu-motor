"""Fotozoeker: zoekt elke nacht foto's bij de uitjes en onthoudt ze in data/photos.json.

Hij leest ook wat de organisator over de soort uitje zegt (schema.org-soort en trefwoorden),
zodat de fabriek het uitje goed kan indelen. Daarvan wordt alleen de conclusie bewaard.

Per uitje, volgens vaste regel 2:
1. De pagina van de organisator over het uitje lezen (eerst robots.txt) en alleen het adres
   van de foto noteren: uit schema.org (Event.image), anders og:image of twitter:image.
   Ook de voorpagina van die website, om de standaardfoto van de hele site te herkennen.
2. Voor uitjes zonder eigen foto: in Wikidata het gebouw of de plaats opzoeken, en foto's
   daarvan op Wikimedia Commons ophalen met maker en licentie: de hoofdfoto en een paar uit
   de Commons-categorie. Zo krijgen uitjes in dezelfde plaats niet allemaal dezelfde foto.

Elke pagina en elke plaats wordt één keer opgezocht en daarna onthouden. Niets gevonden?
Dan probeert hij het na een paar weken opnieuw. Welke foto bij welk uitje komt, beslist
de fabriek (pipeline/v2/photos.py).

Draaien:  python -m collector.event_photos --data data --cache data/photos.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from collections import Counter
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from collector.jsonld_events import _event_type, _is_event, _walk
from collector.site_crawler import USER_AGENT, Fetched, _load_robots, default_fetch
from pipeline.v2 import photos
from pipeline.v2.build import AREA_CENTER, AREA_RADIUS_KM, in_area
from pipeline.v2.classify import page_hints
from pipeline.v2.convert import load_first_party, to_v2

# Wikimedia vraagt om een herkenbare User-Agent met contactadres.
WIKI_USER_AGENT = "UITNU-fotos/1.0 (+https://uitnu.pages.dev/over/)"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

RECHECK_EMPTY_DAYS = 21          # pagina zonder foto: na drie weken opnieuw kijken
RECHECK_HOMEPAGE_DAYS = 30       # standaardfoto van een website: maandelijks verversen
RECHECK_COMMONS_EMPTY_DAYS = 60  # plek of plaats zonder foto op Commons
FORGET_PAGE_DAYS = 30            # pagina's van uitjes die niet meer in de agenda staan
MIN_OG_WIDTH = 300               # kleinere og:image is vrijwel altijd een logo
COMMONS_WIDTH = 1280
PHOTOS_PER_PLACE = 6             # zoveel foto's per gebouw of plaats; elk uitje krijgt er vast één
MIN_PHOTO_WIDTH = 1600           # extra foto's uit een categorie: groot genoeg voor een kaartje
VENUE_MAX_KM = 2.0               # het gebouw in Wikidata moet echt op die plek staan
PLACE_MAX_KM = 15.0              # de plaats in Wikidata moet bij het uitje liggen
MAX_COMMONS_ERRORS = 5           # Wikimedia onbereikbaar: stoppen, volgende nacht verder

# Namen van bestanden die geen foto van een uitje zijn.
SKIP_FILE_HINTS = ("logo", "icon", "favicon", "placeholder", "avatar", "sprite", "spacer",
                   "blank", "default", "fallback")
PLACE_WORDS = ("plaats", "dorp", "stad", "gemeente", "vesting", "buurtschap", "gehucht",
               "village", "town", "city", "municipality", "hamlet")
# Wikidata-soorten voor woonplaatsen (dorp, stad, gemeente, ...).
PLACE_TYPES = {"Q486972", "Q532", "Q3957", "Q515", "Q1549591", "Q2039348", "Q1852859", "Q5084", "Q15284"}
# Bestanden in een Commons-categorie die geen foto van de plek zijn.
NOT_A_PHOTO = re.compile(r"\bkaart|\bmaps?\b|wapen|coat of arms|\blogo|\bvlag\b|\bflag\b|locatie|location|"
                         r"plattegrond|grafsteen|gravestone|tekening|drawing|postcard|ansichtkaart|\bscan\b")


# ---------------------------------------------------------------- foto op de pagina zelf

class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.ld_blocks: list[str] = []
        self._in_ld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").strip().lower()
            content = values.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "script" and values.get("type", "").strip().lower() == "application/ld+json":
            self._in_ld, self._buf = True, []

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._in_ld:
            self.ld_blocks.append("".join(self._buf))
            self._in_ld = False

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)


def _image_value(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        return next((found for found in map(_image_value, value) if found), None)
    if isinstance(value, dict):
        return _image_value(value.get("url") or value.get("contentUrl") or value.get("@id"))
    return None


def usable_image(value: str | None, page_url: str) -> str | None:
    """Een bruikbaar foto-adres, of None voor logo's, iconen en rare waarden."""
    if not value or value.strip().startswith("data:"):
        return None
    url = urljoin(page_url, unescape(value.strip()))
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(url) > 1000:
        return None
    filename = parsed.path.rsplit("/", 1)[-1].casefold()
    if filename.endswith((".svg", ".gif", ".ico")) or any(h in filename for h in SKIP_FILE_HINTS):
        return None
    return url


def _read(html: str, title: str | None) -> tuple[_PageParser, list[dict], bool]:
    """Pagina lezen: meta-tags en de schema.org-uitjes. Staan er meerdere uitjes op, dan alleen
    het uitje met precies deze titel (de derde waarde zegt of dat lukte)."""
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    events: list[dict] = []
    for block in parser.ld_blocks:
        try:
            events.extend(o for o in _walk(json.loads(block)) if _is_event(o))
        except Exception:
            continue
    if len(events) > 1:
        want = photos.norm(title)
        events = [o for o in events if want and photos.norm(str(o.get("name") or "")) == want]
        return parser, events, bool(events)
    return parser, events, True


def page_facts(html: str, title: str | None = None) -> dict:
    """Wat de organisator over de soort uitje zegt: de schema.org-soort en trefwoorden uit de
    omschrijving. Alleen de conclusie wordt bewaard, nooit de tekst zelf (vaste regel 1)."""
    parser, events, ok = _read(html, title)
    if not ok:
        return {}
    facts: dict = {}
    texts = []
    if events:
        kind = _event_type(events[0])
        if kind:
            facts["type"] = kind
        texts.append(_plain(events[0].get("description"), 4000))
        keywords = events[0].get("keywords")
        texts.append(", ".join(map(str, keywords)) if isinstance(keywords, list) else _plain(keywords, 1000))
    for key in ("og:description", "description", "keywords"):
        texts.append(parser.meta.get(key, ""))
    hints = page_hints(" ".join(t for t in texts if t))
    if hints:
        facts["hints"] = hints
    return facts


def extract_page_image(html: str, page_url: str, title: str | None = None) -> tuple[str | None, str | None]:
    """(foto-adres, waar gevonden) uit een pagina: schema.org eerst, dan og:image en twitter:image."""
    parser, events, ok = _read(html, title)
    if not ok:
        return None, None  # meerdere uitjes op één pagina, en geen met deze titel
    for event in events:
        url = usable_image(_image_value(event.get("image")), page_url)
        if url:
            return url, "schema.org"

    width = parser.meta.get("og:image:width", "")
    og_too_small = width.isdigit() and int(width) < MIN_OG_WIDTH
    for key, via in (("og:image", "og:image"), ("og:image:url", "og:image"),
                     ("og:image:secure_url", "og:image"), ("twitter:image", "twitter:image"),
                     ("twitter:image:src", "twitter:image")):
        if og_too_small and key.startswith("og:"):
            continue
        url = usable_image(parser.meta.get(key), page_url)
        if url:
            return url, via
    return None, None


class _Polite:
    """Eerst robots.txt, en een korte pauze tussen twee bezoeken aan dezelfde website."""

    def __init__(self, fetch: Callable[..., Fetched], *, sleeper, clock, delay: float = 0.5,
                 timeout: float = 12):
        self.fetch, self.sleeper, self.clock = fetch, sleeper, clock
        self.delay, self.timeout = delay, timeout
        self.robots: dict[str, object] = {}
        self.last: dict[str, float] = {}

    def get(self, url: str) -> tuple[Fetched | None, str | None, bool]:
        """(pagina, probleem, tijdelijk). Een tijdelijk probleem wordt niet onthouden."""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.robots:
            self.robots[origin] = _load_robots(origin + "/", self.fetch, timeout=self.timeout)[0]
        robots = self.robots[origin]
        if robots.disallow_all and not robots.last_checked:
            return None, "robots.txt niet te lezen", True  # dan niet kijken, wel later opnieuw
        if not robots.can_fetch(USER_AGENT, url):
            return None, "robots.txt staat het niet toe", False
        waited = self.clock() - self.last.get(origin, -1e9)
        if waited < self.delay:
            self.sleeper(self.delay - waited)
        self.last[origin] = self.clock()
        try:
            fetched = self.fetch(url, timeout=self.timeout)
        except Exception as exc:
            return None, f"{type(exc).__name__}", True
        if not (200 <= fetched.status < 300):
            return None, f"HTTP {fetched.status}", fetched.status >= 500 or fetched.status == 429
        if "html" not in fetched.content_type and "<html" not in fetched.text[:500].casefold():
            return None, "geen webpagina", False
        return fetched, None, False


# ---------------------------------------------------------------- Wikidata en Commons

def fetch_json(url: str, params: dict, *, timeout: float = 20) -> dict:
    request = Request(f"{url}?{urlencode(params)}",
                      headers={"User-Agent": WIKI_USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _claims(entity: dict, prop: str) -> list:
    out = []
    for claim in (entity.get("claims") or {}).get(prop) or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if value is not None and claim.get("rank") != "deprecated":
            out.append(value)
    return out


def wikidata_candidates(name: str, fetch_json: Callable[..., dict]) -> list[dict]:
    """Wikidata-items met deze naam die een foto (P18) en coördinaten (P625) hebben."""
    found = fetch_json(WIKIDATA_API, {"action": "wbsearchentities", "search": name, "language": "nl",
                                      "uselang": "nl", "type": "item", "limit": 8, "format": "json"})
    hits = [h for h in found.get("search") or [] if isinstance(h, dict) and h.get("id")]
    if not hits:
        return []
    data = fetch_json(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(h["id"] for h in hits),
                                     "props": "claims", "format": "json"})
    entities = data.get("entities") or {}
    out = []
    for hit in hits:
        entity = entities.get(hit["id"]) or {}
        coords = [c for c in _claims(entity, "P625") if isinstance(c, dict)]
        images = [i for i in _claims(entity, "P18") if isinstance(i, str)]
        if not (coords and images):
            continue
        out.append({
            "id": hit["id"],
            "label": str(hit.get("label") or ""),
            "description": str(hit.get("description") or ""),
            "types": {t.get("id") for t in _claims(entity, "P31") if isinstance(t, dict)},
            "lat": float(coords[0]["latitude"]),
            "lon": float(coords[0]["longitude"]),
            "file": images[0],
            "category": next((c for c in _claims(entity, "P373") if isinstance(c, str)), None),
        })
    return out


def find_place(city: str, near: tuple[float, float], fetch_json: Callable[..., dict],
               max_km: float = PLACE_MAX_KM) -> dict | None:
    """Het dorp of de stad met precies deze naam, het dichtst bij het uitje."""
    want = photos.norm(city)
    best = None
    for item in wikidata_candidates(city, fetch_json):
        if photos.norm(item["label"]) != want:
            continue
        description = item["description"].casefold()
        if not (item["types"] & PLACE_TYPES or any(w in description for w in PLACE_WORDS)):
            continue  # bijvoorbeeld de provincie of een voetbalclub met dezelfde naam
        distance = km(near, (item["lat"], item["lon"]))
        if distance <= max_km and (best is None or distance < best[0]):
            best = (distance, item)
    return best[1] if best else None


def find_venue(venue: str, near: tuple[float, float], fetch_json: Callable[..., dict]) -> dict | None:
    """Het gebouw met deze naam, en alleen als het in Wikidata ook echt op die plek staat."""
    want = photos.norm(venue)
    best = None
    for item in wikidata_candidates(venue, fetch_json):
        label = photos.norm(item["label"])
        shorter = min(label, want, key=len)
        if not (label == want or (len(shorter) >= 5 and (label in want or want in label))):
            continue
        distance = km(near, (item["lat"], item["lon"]))
        if distance <= VENUE_MAX_KM and (best is None or distance < best[0]):
            best = (distance, item)
    return best[1] if best else None


def _plain(value, limit: int = 160) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(unescape(text).split())[:limit]


def _record(title: str, info: dict | None) -> dict | None:
    """Adres, maker en licentie uit het antwoord van Commons (geen tekeningen: svg)."""
    if not info or info.get("mime") == "image/svg+xml":
        return None
    meta = info.get("extmetadata") or {}

    def field(name: str) -> str:
        return _plain((meta.get(name) or {}).get("value"))

    url = info.get("thumburl") or info.get("url")
    if not url:
        return None
    return {
        "file": title,
        "url": url,
        "pageUrl": info.get("descriptionurl"),
        "author": field("Artist") or field("Credit") or None,
        "license": field("LicenseShortName") or None,
        "licenseUrl": field("LicenseUrl") or None,
    }


def commons_info(filename: str, fetch_json: Callable[..., dict]) -> dict | None:
    """Adres, maker en licentie van een foto op Wikimedia Commons."""
    data = fetch_json(COMMONS_API, {"action": "query", "format": "json", "prop": "imageinfo",
                                    "iiprop": "url|extmetadata|mime", "iiurlwidth": COMMONS_WIDTH,
                                    "titles": f"File:{filename}"})
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        return _record(f"File:{filename}", (page.get("imageinfo") or [None])[0])
    return None


def category_photos(category: str, fetch_json: Callable[..., dict], *, limit: int,
                    skip: set[str] = frozenset()) -> list[dict]:
    """Meer foto's uit de Commons-categorie van het gebouw of de plaats: liggende foto's die groot
    genoeg zijn en een maker hebben, zonder kaarten, wapens of logo's. Door de Commons-gemeenschap
    gekeurde foto's ('quality', 'featured') eerst."""
    if limit <= 0:
        return []
    data = fetch_json(COMMONS_API, {"action": "query", "format": "json", "generator": "categorymembers",
                                    "gcmtitle": f"Category:{category}", "gcmtype": "file", "gcmlimit": 40,
                                    "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size",
                                    "iiurlwidth": COMMONS_WIDTH})
    found = []
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        title = str(page.get("title") or "")
        info = (page.get("imageinfo") or [None])[0] or {}
        width, height = info.get("width") or 0, info.get("height") or 0
        if (not title or title in skip or info.get("mime") != "image/jpeg" or NOT_A_PHOTO.search(title.casefold())
                or width < MIN_PHOTO_WIDTH or not height or not 1.2 <= width / height <= 2.2):
            continue
        record = _record(title, info)
        if not record or not record["author"]:
            continue
        assessed = str(((info.get("extmetadata") or {}).get("Assessments") or {}).get("value") or "")
        rank = 2 if re.search(r"featured|potd|poty", assessed) else 1 if "quality" in assessed else 0
        found.append((-rank, title, record))
    found.sort(key=lambda row: row[:2])
    return [record for _, _, record in found[:limit]]


def commons_photos(item: dict, fetch_json: Callable[..., dict], limit: int = PHOTOS_PER_PLACE) -> list[dict]:
    """De foto's van een gebouw of plaats: de hoofdfoto uit Wikidata, aangevuld uit de Commons-categorie."""
    main = commons_info(item["file"], fetch_json)
    out = [main] if main else []
    if item.get("category"):
        out += category_photos(item["category"], fetch_json, limit=limit - len(out),
                               skip={main["file"]} if main else set())
    return out


# ---------------------------------------------------------------- de nachtelijke ronde

def load_cache(path: str | Path) -> dict:
    path = Path(path)
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for key in ("pages", "homepages", "commons"):
        cache.setdefault(key, {})
    cache["version"] = 1
    return cache


def save_cache(path: str | Path, cache: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _age_days(entry: dict, today: date) -> int:
    try:
        return (today - date.fromisoformat(str(entry.get("checkedAt")))).days
    except ValueError:
        return 10_000


def _due(entry: dict | None, today: date, recheck_days: int, field: str) -> bool:
    if entry is None:
        return True
    return not entry.get(field) and _age_days(entry, today) >= recheck_days


def _commons_due(entry: dict | None, today: date) -> bool:
    if entry and entry.get("url"):
        return "photos" not in entry  # uit de tijd van één foto per plaats: één keer aanvullen
    return _due(entry, today, RECHECK_COMMONS_EMPTY_DAYS, "url")


def run(data_dir: str | Path, cache_path: str | Path, *, today: date | None = None,
        fetch: Callable[..., Fetched] = default_fetch, fetch_json: Callable[..., dict] = fetch_json,
        sleeper=time.sleep, clock=time.monotonic, max_pages: int = 150, max_lookups: int = 60,
        timeout: float = 12, budget_seconds: float = 8 * 60) -> Counter:
    """Eén nachtelijke ronde. Stopt op tijd (budget) en bewaart tussendoor, zodat een
    afgebroken ronde nooit werk kwijtraakt; de volgende nacht gaat hij verder."""
    today = today or date.today()
    deadline = clock() + budget_seconds

    def out_of_time() -> bool:
        return clock() >= deadline

    stamp = today.isoformat()
    cache = load_cache(cache_path)
    events = [e for e in (to_v2(r, today) for r in load_first_party(Path(data_dir))) if e and in_area(e)]
    lists = photos.list_pages(events)
    polite = _Polite(fetch, sleeper=sleeper, clock=clock, timeout=timeout)
    stats: Counter = Counter()

    # 1. De pagina van elk uitje (één keer, daarna onthouden).
    for event in events:
        for page in photos.event_pages(event):
            if page in lists or not _due(cache["pages"].get(page), today, RECHECK_EMPTY_DAYS, "image"):
                continue
            if stats["pagina's bekeken"] >= max_pages or out_of_time():
                break
            fetched, problem, temporary = polite.get(page)
            stats["pagina's bekeken"] += 1
            if temporary:
                stats["tijdelijk onbereikbaar"] += 1
                continue
            image, via = extract_page_image(fetched.text, fetched.url, event.get("title")) if fetched else (None, None)
            facts = page_facts(fetched.text, event.get("title")) if fetched else {}
            cache["pages"][page] = {"image": image, "via": via, "checkedAt": stamp, **facts,
                                    **({"note": problem} if problem else {})}
            stats["foto's van organisatoren gevonden"] += bool(image)
            if stats["pagina's bekeken"] % 25 == 0:
                save_cache(cache_path, cache)

    # 2. De voorpagina van elke website met foto's: welke foto staat daar standaard?
    for host, page in {photos.host_of(p): p for p, v in cache["pages"].items() if v.get("image")}.items():
        entry = cache["homepages"].get(host)
        if entry and _age_days(entry, today) < RECHECK_HOMEPAGE_DAYS:
            continue
        if stats["pagina's bekeken"] >= max_pages or out_of_time():
            break
        parsed = urlparse(page)
        home = f"{parsed.scheme}://{parsed.netloc}/"
        fetched, problem, temporary = polite.get(home)
        stats["pagina's bekeken"] += 1
        if temporary:
            continue
        image = extract_page_image(fetched.text, fetched.url)[0] if fetched else None
        cache["homepages"][host] = {"image": image, "checkedAt": stamp, **({"note": problem} if problem else {})}

    save_cache(cache_path, cache)

    # 3. Geen eigen foto? Dan foto's van het gebouw of de plaats op Wikimedia Commons.
    errors = 0
    for event in events:
        if errors >= MAX_COMMONS_ERRORS or stats["opzoekingen op Wikimedia"] >= max_lookups or out_of_time():
            break  # Wikimedia onbereikbaar, of genoeg voor vannacht: morgen verder
        chosen = photos.choose_photo(event, cache, lists=lists, names={})
        if chosen and chosen["type"] == "organisator":
            continue
        venue, city = photos.venue_name(event), event["venue"].get("city")
        lat, lon = event["venue"].get("lat"), event["venue"].get("lon")
        near = (float(lat), float(lon)) if lat is not None and lon is not None else None
        todo = []
        if venue and near:
            todo.append((photos.venue_key(event), lambda: find_venue(venue, near, fetch_json)))
        if city:
            todo.append((photos.place_key(event),
                         lambda: find_place(city, near or AREA_CENTER, fetch_json,
                                            max_km=PLACE_MAX_KM if near else AREA_RADIUS_KM + 15)))
        for key, lookup in todo:
            old = cache["commons"].get(key)
            if not _commons_due(old, today):
                if old.get("url"):
                    break  # deze heeft al foto's; de plaats is dan niet meer nodig
                continue
            try:
                item = lookup()
                found = commons_photos(item, fetch_json) if item else []
            except Exception:
                errors += 1
                break
            stats["opzoekingen op Wikimedia"] += 1
            if not found and old and old.get("url"):
                found = [{k: old[k] for k in ("file", "url", "pageUrl", "author", "license", "licenseUrl") if k in old}]
            entry = {"url": found[0]["url"], "photos": found} if found else {"url": None}
            cache["commons"][key] = {**entry, "checkedAt": stamp, **({"wikidata": item["id"]} if item else {})}
            if found:
                stats["foto's van Wikimedia gevonden"] += len(found)
                break

    # 4. Pagina's van uitjes die al een maand niet meer in de agenda staan, vergeten.
    current = {p for e in events for p in photos.event_pages(e)}
    for page in [p for p, v in cache["pages"].items() if p not in current and _age_days(v, today) >= FORGET_PAGE_DAYS]:
        del cache["pages"][page]

    cache["updated"] = stamp
    save_cache(cache_path, cache)
    if errors:
        stats["fouten bij Wikimedia"] = errors
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UITNU: foto's bij de uitjes zoeken")
    parser.add_argument("--data", default="data")
    parser.add_argument("--cache", default="data/photos.json")
    parser.add_argument("--max-pages", type=int, default=150)
    parser.add_argument("--max-lookups", type=int, default=60)
    args = parser.parse_args(argv)
    stats = run(args.data, args.cache, max_pages=args.max_pages, max_lookups=args.max_lookups)
    print("Foto's zoeken klaar.")
    for name, value in stats.items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
