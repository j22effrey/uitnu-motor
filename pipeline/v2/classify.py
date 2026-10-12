"""Eén indeling voor heel UITNU.

Regels, in deze volgorde:
1. handmatige correctie (overrides.json): per uitje of op naam, altijd met een reden;
2. trefwoorden in titel en beschrijving, met vaste uitzonderingen;
3. wat de organisator zelf op de pagina van het uitje zet (soort volgens schema.org, trefwoorden);
4. een regel per locatie of bron (website van een podium);
5. de oude categorie van de bron als hint;
6. anders 'overig'.

Festival: alleen als het echt een festival is (vaste regel 3): een groot terrein of meerdere zalen,
meerdere podia en vooral verschillende artiesten. Een naam met 'festival' is daar geen bewijs voor.
Bewijs is: de organisator noemt meerdere podia, een line-up of een festivalterrein, of het staat
in het festivalregister (overrides.json, 'namen', met reden).

Indelen labelt alleen: deze module laat nooit een evenement weg. Alleen not_an_outing() zegt
of iets helemaal geen uitje is (een gewone kerkdienst); dat beslist de fabriek.
Elke uitkomst bevat methode, reden en zekerheid, zodat fouten na te speuren zijn.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .kinds import DISCIPLINE_HINTS, KINDS, LEGACY_HINTS, SCHEMA_KIND_HINTS


def normalize(text: str) -> str:
    """Kleine letters, zonder accenten en met enkele spaties."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _compile(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


# Trefwoorden per soort. Nederlandse samenstellingen ("stadswandeling") zijn de reden
# dat sommige patronen bewust zonder woordgrens aan het begin werken.
PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "film": _compile([r"\bfilm", r"bioscoop", r"cinema", r"filmhuis", r"documentaire", r"cinekid"]),
    "sport": _compile([
        r"hardloop", r"(?<!ver)(?<!door)(?<!aan)(?<!uit)loop\b", r"run\b", r"\btrail", r"toertocht", r"\d+\s?(km|kilometer|mijl)\b", r"\bmijl\b", r"marathon",
        r"triatlon", r"wedstrijd", r"toernooi", r"regatta", r"roeiwedstrijd", r"schaats",
        r"wielren", r"mountainbike", r"\bmtb\b", r"voetbal", r"korfbal", r"handbal", r"hockey",
        r"zwemtocht", r"sportdag", r"\brace\b", r"obstacle", r"gymnastiek", r"biljart", r"\bsjoel", r"koersbal",
    ]),
    "natuur": _compile([
        r"wandel", r"excursie", r"natuur", r"vogel", r"sterren", r"paddenstoel", r"wildpluk",
        r"kwelder", r"wadlo", r"boswachter", r"fietstocht", r"struin", r"nacht van de nacht",
        r"huifkar", r"landgoed", r"vaartocht", r"zwerftocht", r"rondvaart", r"nationaal park",
        r"kuier", r"pelgrim",
    ]),
    "eten": _compile([
        r"culinair", r"food", r"proeverij", r"\bproeven\b", r"\bwijn", r"\bbier(?!run)", r"smaak",
        r"high tea", r"brunch", r"\bdiner\b", r"barbecue", r"\bbbq\b", r"kookworkshop",
        r"whisk(e)?y", r"cocktail", r"\bgin\b", r"(samen|gezamenlijk) eten", r"aan de kook", r"stamppot",
        r"maaltijd", r"\bkoffie(?!concert)", r"\blunch", r"vrijmibo", r"borrel",
    ]),
    "markt": _compile([
        r"markt", r"(?<=\w)maart\b", r"braderie", r"beurs", r"fair\b", r"salon\b",
        r"reis ?event", r"reizen\b.*\bevent", r"rommel", r"vlooien", r"snuffel", r"krystmerk", r"\bmerke\b",
    ]),
    "feest": _compile([
        r"kermis", r"feest", r"koningsdag", r"koningsnacht", r"sinterklaas", r"intocht",
        r"carnaval", r"optocht", r"lampion", r"halloween", r"spooktocht", r"lichtjes",
        r"vuurwerk", r"oud en nieuw", r"line ?dance", r"volksdans", r"\bquiz", r"gezellige avond", r"gesellige jun",
        r"oktoberfest", r"oktofest", r"nieuwjaarsduik",
    ]),
    "theater": _compile([
        r"theater", r"voorstelling", r"toneel", r"cabaret", r"comedy", r"stand-?up",
        r"musical", r"\bopera\b", r"ballet", r"\bdans(voorstelling|theater)?\b",
        r"poppen(kast|theater)", r"circus",
    ]),
    "muziek": _compile([
        r"concert", r"\blive\b", r"band\b", r"\bkoor", r"koren", r"orkest", r"\bdj\b", r"optreden",
        r"gospel", r"fanfare", r"shanty", r"smartlap",
        r"clubnacht", r"\bparty\b", r"\bjazz", r"\bpop\b", r"\brock", r"\bblues", r"\bmetal\b",
        r"hip-?hop", r"techno", r"\bhouse\b", r"recital", r"\borgel", r"cantate", r"muziek",
        r"singer-?songwriter", r"\brave\b", r"taptoe", r"\btrio\b", r"kwartet", r"kwintet", r"\bensemble\b",
        r"worship", r"\bmusic\b",
    ]),
    "kunst": _compile([
        r"tentoonstelling", r"expositie", r"\bexpo\b", r"museum", r"galerie", r"\bkunst",
        r"atelier", r"monument", r"erfgoed", r"open kerk", r"kerkpad", r"rondleiding", r"beelden van",
        r"beeldhouw", r"historisch",
    ]),
    "lezing": _compile([
        r"lezing", r"workshop", r"cursus", r"masterclass", r"\bdebat\b",
        r"symposium", r"voorlees", r"\bcollege\b", r"leerhuis", r"gespreksgroep", r"meditatie",
        r"repair ?caf", r"bloemschik", r"verkeersregels", r"creatief caf", r"handwerk", r"informatie ?avond",
        r"info ?avond",
    ]),
    # Uitjes die vooral om kinderen draaien. Een voorstelling of concert voor kinderen blijft
    # theater of muziek, met het label 'Voor kinderen'.
    "kinderen": _compile([
        r"springkussen", r"kinderboerderij", r"kinder(feest|disco|middag|activiteit|maand|speel|dag)",
        r"\bkids?(club|dag|feest|middag)?\b", r"knutsel", r"schmink", r"\bpeuter", r"\bkleuter",
        r"speeltuin", r"ballonnen", r"klimpark", r"indoor ?speel",
    ]),
}

# Volgorde waarin soorten winnen als meerdere trefwoorden passen.
PRIORITY = [
    "film", "sport", "lezing", "natuur", "eten", "markt", "kinderen", "feest", "theater", "muziek", "kunst",
]

FESTIVAL = re.compile(r"festival")
# Bewijs van een echt festival: meerdere podia of zalen, een line-up of een festivalterrein.
STAGES = re.compile(r"\bpodia\b|meerdere podium|\bstages\b|line-?up|festival-? ?terrein|meerdere zalen")
CLUBNIGHT = re.compile(r"\bdj\b|clubnacht|\bparty\b|techno|\bhouse\b|\brave\b")
CHOIR_ORGAN = re.compile(r"\bkoor|koren|\borgel")
FREE = re.compile(r"gratis|vrije? entree|\bfree\b")
CHILDREN = re.compile(r"kinder|kids|familie|jeugd|peuter|kleuter|sinterklaas|speurtocht|speurwandeling|springkussen"
                      r"|\(\s*[2-9]\s*\+\s*\)|vanaf [2-9] jaar")  # (6+) of 'vanaf 6 jaar': voor kinderen
THEATER_FESTIVAL = re.compile(r"cabaret|theater|comedy|toneel")
OUTDOOR = re.compile(r"\bbuiten|openlucht|strand")
# Geen uitje: gewone kerkdiensten en gebedsbijeenkomsten (wel: concerten en open dagen in kerken).
NOT_AN_OUTING = re.compile(r"\b(eredienst(?:en)?|kerkdienst(?:en)?|zondagsdienst|ochtenddienst|middagdienst|avonddienst"
                           r"|gebedsdienst|gebedsuur|gebedskring|bijbelstudie|bijbelkring|eucharistieviering"
                           r"|woord- en communieviering|rouwdienst|uitvaartdienst|kerst(?:nacht)?dienst|tsjerketsjinst"
                           r"|gemeenteavond|gearkomste|redactievergadering"
                           # mededelingen voor het dorp, geen uitje
                           r"|oud papier|collecte\w*|kopij|wintertijd|zomertijd"
                           # vergaderingen en bijeenkomsten voor leden of vrijwilligers: niet voor publiek
                           r"|ledenvergadering|jaarvergadering|bestuursvergadering|alv|vrijwilligers\w*|besloten"
                           # mededelingen: iets is dicht (de huisartsenpraktijk, de bibliotheek)
                           r"|(?:\w*praktijk|apotheek|bibliotheek|balie|kantoor|winkel|dorpshuis|kerk) (?:is )?gesloten)\b")
# Knoppen en kopjes van een website die als naam van een uitje zijn meegekomen.
NOT_A_TITLE = re.compile(r"^(?:start|begin|aanvang|selecteer (?:een )?(?:tijdstip|datum|dag)|kies (?:een )?(?:tijdstip|datum|dag)"
                         r"|bestel (?:je )?tickets?|koop (?:je )?tickets?|tickets?|meer info(?:rmatie)?|lees meer|bekijk"
                         r"|reserveren|aanmelden|inschrijven)$")

# Websites die vrijwel alleen een soort aanbieden. Alleen gebruikt als trefwoorden niets opleveren.
VENUE_RULES: dict[str, str] = {
    "simplon.nl": "muziek",
    "vera-groningen.nl": "muziek",
}


def _matches(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for kind, patterns in PATTERNS.items():
        hits = [m.group(0) for p in patterns if (m := p.search(text))]
        if hits:
            found[kind] = hits
    return found


def _host(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def _rule_for(rules: dict[str, str], host: str) -> str | None:
    """De soort bij een website, ook voor een onderdeel ervan (tickets.theater.nl -> theater.nl)."""
    parts = host.split(".")
    for start in range(0, max(1, len(parts) - 1)):
        kind = rules.get(".".join(parts[start:]))
        if kind:
            return kind
    return None


def venue_key(name: str | None, city: str | None) -> str:
    """Sleutel voor 'deze zaal in deze plaats' (de vaste plek van een bron)."""
    return f"plek:{normalize(name or '')}|{normalize(city or '')}"


def _is_multiday(event: dict) -> bool:
    for occ in event.get("occurrences") or []:
        if occ.get("endDate") and occ.get("endDate") != occ.get("date"):
            return True
    return False


def parse_overrides(raw: dict | None) -> tuple[dict[str, tuple[str, str]], list[tuple[re.Pattern[str], str, str, bool]]]:
    """overrides.json lezen. Nieuwe vorm: {"uitjes": {id: {"soort", "reden"}}, "namen": [{"naam", "soort", "reden"}]}.
    De oude vorm {id: soort} werkt ook nog."""
    ids: dict[str, tuple[str, str]] = {}
    names: list[tuple[re.Pattern[str], str, str, bool]] = []
    if not raw:
        return ids, names
    by_id = raw.get("uitjes", {}) if ("uitjes" in raw or "namen" in raw) else raw
    for key, value in by_id.items():
        if isinstance(value, str):
            ids[key] = (value, "handmatige correctie in overrides.json")
        elif isinstance(value, dict) and value.get("soort"):
            ids[key] = (value["soort"], value.get("reden") or "handmatige correctie in overrides.json")
    for entry in raw.get("namen", []) if isinstance(raw.get("namen"), list) else []:
        if isinstance(entry, dict) and entry.get("naam") and entry.get("soort"):
            names.append((re.compile(normalize(entry["naam"])), entry["soort"], entry.get("reden") or "vaste regel op naam",
                          bool(entry.get("nakijken"))))
    return ids, names


def classify(event: dict, overrides: dict | None = None,
             venue_rules: dict[str, str] | None = None) -> dict:
    """Geeft {kind, tags, method, reason, confidence} terug.

    overrides: de inhoud van overrides.json (per uitje of op naam).
    venue_rules: extra 'website -> soort' uit de bronnenlijst (veld kindHint), naast VENUE_RULES.
    Het uitje mag 'schemaType' en 'pageHints' hebben: wat de organisator zelf op de pagina zet.
    """
    title = event.get("title") or ""
    text = normalize(" ".join([title, event.get("description") or ""]))
    page = event.get("pageHints") if isinstance(event.get("pageHints"), dict) else {}
    tags: set[str] = set()

    price = normalize(event.get("price") or "")
    if FREE.search(price) or FREE.search(normalize(title)):
        tags.add("gratis")
    if CHILDREN.search(text) or page.get("soort") == "kinderen":
        tags.add("kinderen")
    if _is_multiday(event):
        tags.add("meerdaags")
    if OUTDOOR.search(text):
        tags.add("buiten")

    def result(kind: str, method: str, reason: str, confidence: float, check: bool = False) -> dict:
        if kind == "natuur":
            tags.add("buiten")
        verdict = {
            "kind": kind,
            "tags": sorted(tags),
            "method": method,
            "reason": reason,
            "confidence": confidence,
        }
        if check:
            verdict["nakijken"] = True  # vuistregel: dit uitje nog een keer bekijken
        return verdict

    # 1. Handmatige correctie: per uitje, of op naam (bijvoorbeeld het festivalregister)
    ids, names = parse_overrides(overrides)
    if event.get("id") in ids:
        kind, reason = ids[event["id"]]
        if kind in KINDS:
            return result(kind, "correctie", reason, 1.0)
    for pattern, kind, reason, check in names:
        if kind in KINDS and pattern.search(normalize(title)):
            return result(kind, "correctie", reason, 0.9 if check else 1.0, check)

    found = _matches(text)
    in_title = _matches(normalize(title))
    race = "sport" in found
    has_festival = bool(FESTIVAL.search(text))
    stages = STAGES.search(text)

    # 2a. 'Festival' in de naam: alleen een festival met bewijs van meerdere podia of een line-up.
    # Er komt geen label 'festival' bij: op de site betekent festival alleen de echte festivals.
    if has_festival:
        if "film" in in_title:
            return result("film", "trefwoord", "filmfestival telt als film", 0.9)
        if "eten" in in_title:
            return result("eten", "trefwoord", "festival met één discipline: eten", 0.85)
        if THEATER_FESTIVAL.search(normalize(title)):
            return result("theater", "trefwoord", "theater- of cabaretfestival: voorstellingen, geen festivalterrein", 0.8)
        if stages:
            return result("festival", "trefwoord", f"festival met bewijs: '{stages.group(0)}'", 0.85)
        if page.get("podia"):
            return result("festival", "organisator", f"festival: de organisator noemt '{page['podia']}'", 0.8)
        if CLUBNIGHT.search(text):
            return result("muziek", "trefwoord", "één avond met dj of clubnacht: geen festival", 0.8)
        if CHOIR_ORGAN.search(text):
            return result("muziek", "trefwoord", "festival met één discipline: muziek", 0.8)
        # Geen bewijs: dan is het geen festival, en kijken we gewoon wat het wel is.

    # 2b. Wandelingen en excursies zijn natuur, behalve bij een echte wedstrijd
    if "natuur" in found and race:
        return result("sport", "trefwoord", f"wedstrijd ({found['sport'][0]}) in de natuur", 0.85)
    for kind in PRIORITY:
        if kind in found:
            return result(kind, "trefwoord", f"trefwoord '{found[kind][0]}'", 0.8)

    # 3. Wat de organisator zelf op de pagina van het uitje zet
    schema_kind = SCHEMA_KIND_HINTS.get(str(event.get("schemaType") or ""))
    if schema_kind:
        return result(schema_kind, "organisator", f"de organisator noemt het een {event['schemaType']}", 0.75)
    if page.get("soort") in KINDS and page.get("soort") != "festival":
        return result(page["soort"], "organisator", f"trefwoord '{page.get('woord')}' op de pagina van de organisator", 0.65)

    # 4. Locatie of bron
    rules = {**(venue_rules or {}), **VENUE_RULES}
    for url in (event.get("url"), *(s.get("url") for s in event.get("sources") or [])):
        kind = _rule_for(rules, _host(url or ""))
        if kind in KINDS:
            return result(kind, "locatie", f"website {_host(url or '')}", 0.6)
    venue = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    kind = rules.get(venue_key(venue.get("name"), venue.get("city")))
    if venue.get("name") and kind in KINDS:
        return result(kind, "locatie", f"zaal {venue['name']}", 0.6)

    # 5. Oude categorie of discipline als hint (geen 'festival' zonder bewijs)
    hint = LEGACY_HINTS.get(event.get("legacyCategory") or "")
    if hint and hint != "festival":
        return result(hint, "bronhint", f"oude categorie '{event.get('legacyCategory')}'", 0.5)
    hint = DISCIPLINE_HINTS.get(event.get("legacyDiscipline") or "")
    if hint:
        return result(hint, "bronhint", f"discipline '{event.get('legacyDiscipline')}'", 0.5)

    # 6. Niets gevonden
    return result("overig", "geen", "geen trefwoord, organisatorgegevens, locatie of hint", 0.2)


def page_hints(text: str) -> dict:
    """Wat een tekst van de organisator over de soort zegt, zonder de tekst zelf te bewaren:
    alleen de soort, het ene trefwoord en of er meerdere podia of een line-up genoemd worden."""
    text = normalize(text)
    hints: dict = {}
    found = _matches(text)
    for kind in PRIORITY:
        if kind in found:
            hints = {"soort": kind, "woord": found[kind][0]}
            break
    stages = STAGES.search(text)
    if stages and FESTIVAL.search(text):
        hints["podia"] = stages.group(0)
    return hints


def not_an_outing(event: dict) -> str | None:
    """De reden waarom dit geen uitje is (een gewone kerkdienst), of None."""
    title = normalize(event.get("title") or "")
    if NOT_A_TITLE.match(title.strip(" .:!")):
        return f"geen naam van een uitje: '{event.get('title')}'"
    hit = NOT_AN_OUTING.search(title)
    return f"geen uitje: '{hit.group(0)}'" if hit else None
