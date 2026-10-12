# UITNU motor

UITNU is een uitagenda voor Groningen en omgeving: alles binnen 60 km van Groningen-centrum.

## Communicatie

- Antwoord altijd in het Nederlands, eenvoudig uitgelegd. De eigenaar is geen programmeur.

## Repo's

- `j22effrey/uitnu-motor` (openbaar, deze repo): de motor. Leidend voor `collector/`, `pipeline/`
  en `tests/v2/`. Draait elke nacht via `.github/workflows/motor.yml` en publiceert
  `data/v2/events.json` (met `data/v2/status.json` als verslag).
- `j22effrey/uitnu` (privé), branch `v2`: de site in `site/` (Astro). Cloudflare Pages bouwt die
  automatisch en haalt de agenda uit deze motor.

## Vaste regels

1. **Bronnen.** Nooit VisitGroningen, Kultuuragenda of andere uitagenda's of verzamelsites als bron.
   Alleen organisatoren, podia, musea, dorpshuizen en gemeenten. Alleen feiten overnemen (naam,
   datum, tijd, plek, link), nooit teksten kopiëren. De lijst met uitgesloten sites staat in
   `EXCLUDED_HOSTS` in `collector/discover_venues.py`.
2. **robots.txt respecteren.** Foto's: die van de organisator rechtstreeks tonen met naam, anders
   Wikimedia Commons met maker en licentie, anders de eigen illustratie.
3. **Festival** betekent alleen: meerdere podia op een eigen, afgezet terrein. Twijfelgevallen eerst
   uitzoeken, en de reden vastleggen in `pipeline/v2/overrides.json`.
4. **Werkwijze.** Altijd eerst testen (`python -m pytest tests/v2`), dan een pull request met uitleg
   in gewone taal.

## Hoe de motor werkt (kort)

1. `collector/discover_venues.py`: zoekt nieuwe websites via OpenStreetMap en Wikidata
   (`data/source_candidates.json`).
2. `collector/source_probe.py`: test of een website een leesbare agenda heeft.
3. `collector/auto_activate.py`: zet geschikte bronnen aan in `collector/web_crawl_sources.json`.
4. `pipeline/stage_active_sources.py` + `pipeline/build_auto_events.py`: halen de agenda's op
   en schrijven `data/auto_events.json`.
5. `pipeline/v2/build.py`: voegt alles samen, deelt in, keurt (`gate.py`) en publiceert.
