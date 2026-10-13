# UITNU motor

UITNU is de werknaam van een uitagenda; de definitieve naam komt later. De proef draait in één
regio: alles binnen 60 km van Groningen-centrum (`AREA_CENTER` en `AREA_RADIUS_KM` in
`pipeline/v2/build.py`). Daarna wordt het landelijk, dus bouw niets dat alleen voor Groningen werkt.

## Communicatie

- Antwoord altijd in het Nederlands, eenvoudig uitgelegd. De eigenaar is geen programmeur.

## Repo's

- `j22effrey/uitnu-motor` (openbaar, deze repo): de motor. Leidend voor `collector/`, `pipeline/`
  en `tests/v2/`. Draait elke nacht via `.github/workflows/motor.yml` en publiceert
  `data/v2/events.json` (met `data/v2/status.json` als verslag en `data/v2/twijfel.json` als lijst
  met uitjes waarvan de soort nog nagekeken moet worden).
- `j22effrey/uitnu` (privé), branch `v2`: de site in `site/` (Astro). Cloudflare Pages bouwt die
  automatisch en haalt de agenda uit deze motor.

## Vaste regels

1. **Bronnen.** Nooit VisitGroningen, Kultuuragenda of andere uitagenda's of verzamelsites als bron.
   Alleen organisatoren, podia, musea, dorpshuizen en gemeenten. Alleen feiten overnemen (naam,
   datum, tijd, plek, link), nooit teksten kopiëren. De lijst met uitgesloten sites staat in
   `EXCLUDED_HOSTS` in `collector/discover_venues.py`.
2. **robots.txt respecteren.** Foto's: die van de organisator rechtstreeks tonen met naam, anders
   Wikimedia Commons met maker en licentie (eerst het gebouw, dan de plaats). Geen illustraties:
   zonder foto toont de site een kaart met alleen tekst.
3. **Festival** betekent alleen: een groot terrein (of meerdere zalen of locaties), meerdere podia en
   vooral verschillende artiesten. 'Festival' in de naam is geen bewijs: een springkussenfestival is
   'kinderen', een whiskyfestival 'eten'. Twijfelgevallen eerst uitzoeken, en de reden vastleggen in
   `pipeline/v2/overrides.json` (festivalregister onder `namen`, altijd met `reden`).
4. **Werkwijze.** Altijd eerst testen (`python -m pytest tests/v2`), dan een pull request met uitleg
   in gewone taal. Claude voegt die pull request daarna zelf samen (afspraak met de eigenaar van
   13 oktober 2026), maar alleen als de tests slagen en, bij een verandering aan het ophalen of
   indelen, een proef met de echte websites door de keuring komt. Daarna meldt Claude in gewone taal
   wat er is veranderd.

## Hoe de motor werkt (kort)

1. `collector/discover_venues.py`: zoekt nieuwe websites via OpenStreetMap (podia, dorpshuizen,
   musea, cafés, verenigingen, gemeentehuizen, en dorpen met een eigen website) en Wikidata
   (festivals, dorpen en gemeenten), plus de tips in `collector/tips.json` en de gevonden
   dorpswebsites (`data/source_candidates.json`).
   `collector/village_sites.py` loopt elke plaats in het werkgebied na (eens per drie maanden): het
   probeert veelgebruikte websitenamen (eenrum.nl, dorpsbelangeneenrum.nl, ...), kijkt (met respect
   voor robots.txt) of de site echt bij die plaats hoort, en bewaart het oordeel in
   `data/dorpssites.json` ('dorpssite', 'twijfel' of 'nee', altijd met een reden). Alleen
   'dorpssite' gaat vanzelf de wachtrij in; twijfelgevallen eerst nakijken (dan als tip toevoegen).
2. `collector/source_probe.py`: test of een website een leesbare agenda heeft (ook via de link
   naar de agenda op de voorpagina). Volgorde: tips, nieuwe dorpswebsites, websites die een oudere
   test afwees, nieuwe websites, dan herkansingen na een wachttijd. Geen robots.txt betekent: welkom.
3. `collector/auto_activate.py`: zet geschikte bronnen aan in `collector/web_crawl_sources.json`.
   Een dorpswebsite krijgt de plaats van het dorp mee, voor uitjes zonder eigen plaats.
4. `pipeline/stage_active_sources.py` + `pipeline/build_auto_events.py`: halen de agenda's op
   en schrijven `data/auto_events.json`. Na 25 minuten rondt de motor af met wat er is; een bron
   die niet af kwam (of storing had), houdt zijn uitjes van de vorige keer.
5. `collector/event_photos.py`: zoekt foto's (organisator, anders meerdere foto's per gebouw of
   plaats van Wikimedia Commons) en onthoudt ze in `data/photos.json`. Hij noteert ook wat de
   organisator zelf over de soort zegt (alleen de conclusie, geen tekst). `pipeline/v2/photos.py`
   kiest per uitje de foto; uitjes in dezelfde plaats krijgen om de beurt een andere foto.
6. `pipeline/v2/build.py`: voegt alles samen, laat weg wat geen uitje is (gewone kerkdiensten,
   zaalverhuur, vergaderingen en bestuur, mededelingen zoals de afvalkalender, een titel die alleen
   een club of vaste ontmoeting noemt zoals '50 plus club' of 'Inloopmiddag', en vaste activiteiten
   die elke week terugkomen zoals klaverjassen of gym; voorstellingen, concerten, films, markten,
   tentoonstellingen en natuuruitjes blijven altijd staan), deelt in (`classify.py`), kiest foto's,
   keurt (`gate.py`) en publiceert. Uitjes verder dan anderhalf jaar vooruit zijn een leesfout.

## Ontbreekt er een uitje?

- Staat het op de eigen website van een organisator, dorp of gemeente? Zet die website in
  `collector/tips.json` (met `naam`, `reden` en `datum`); de motor test hem de volgende ronde als eerste.
- Staat het alleen op Facebook of een poster? Zet de feiten (naam, datum, tijd, plaats, prijs, link)
  in `data/events.json` met een `sourceNote` waar het vandaan komt. Een plaatsnaam is genoeg: de
  motor zet zelf de kaartpin (`collector/geocode_curated.py`). Facebook zelf lezen we nooit.

## Indeling (soorten)

Muziek, Festival, Theater en comedy, Film, Markt en beurs, Feest en kermis, Kinderen en familie,
Sport, Natuur en buiten, Kunst en erfgoed, Lezing en workshop, Eten en drinken, Overig
(`pipeline/v2/kinds.py`). Volgorde van beslissen: correctie of festivalregister, trefwoorden, wat de
organisator zelf op de pagina zet (schema.org) of de rubriek in de link (`/cursusprogramma/...`), de
soort van het podium, oude hints, anders 'overig'.
Elke uitkomst heeft een reden. De testset staat in `tests/v2/testset_soorten.json`.
