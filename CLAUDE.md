# UITNU motor

UITNU is de werknaam van een uitagenda; de definitieve naam komt later. Het werkgebied is
Noord-Nederland: de provincies Groningen, Fryslân en Drenthe, plus een rand van 10 km over de grens
(`AREA_PROVINCES` en `MARGIN_KM` in `pipeline/area.py`; de grenzen staan in `pipeline/provincies.json`,
van het CBS). Daarna wordt het landelijk (een langer lijstje provincies), dus bouw niets dat alleen voor
één regio werkt. Eerder was het 60 km rond Groningen-centrum.

## Communicatie

- Antwoord altijd in het Nederlands, eenvoudig uitgelegd. De eigenaar is geen programmeur.

## Repo's

- `j22effrey/uitnu-motor` (openbaar, deze repo): de motor. Leidend voor `collector/`, `pipeline/`
  en `tests/v2/`. Draait elke drie uur via `.github/workflows/motor.yml` (GitHub slaat geplande rondes
  soms over of begint later; dan komt de volgende gewoon) en publiceert
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
4. **Alleen uitjes voor het grote publiek** (afspraak met de eigenaar, 13 oktober 2026). Geen vaste
   les, training of oefenavond van een club of groep (koor, fanfare, wandelgroep, yoga, klaverjassen,
   koffieochtend), geen competitiewedstrijden van amateurteams ('Covos DS1 – VC Sneek DS2'), niets
   alleen voor leden, dorpsbewoners of de ouderen van het dorp, en nooit seks- of naaktfeesten. Staat
   er iets openbaars bij (concert, toernooi, open dag, voorstelling), dan blijft het staan
   (`CLUB_SESSION`, `TEAM_MATCH`, `MEMBERS_ONLY`, `SENIORS_ONLY` en `ADULT_ONLY` in `classify.py`).
   Ook **alleen noemenswaardige uitjes** (afspraak van 14 oktober 2026, voorbeeld Westerlee): niet wat
   een dorpshuis voor de eigen mensen doet (koffie, soep of friet, borrel, dorpsmaaltijd, dorpskamer,
   handwerk- of taalcafé), geen hulp of cursus (repair café, mantelzorgcafé, cursus computer of
   reanimatie), geen inspraak of informatieavond (dorpsvisie, woningbouw), geen clubspel of competitie
   (biljarten, darten, clubkampioenschap, slottoernooi), geen mededelingen (afgelast, inleverdatum,
   milieubus, verkiezingen) en geen menu van een website ('Privacybeleid', 'Filteren'). Een toernooi,
   drive, workshop, lezing of optreden blijft staan (`CLUB_GAME`, `CLUB_INTERNAL`, `VILLAGE_ROUTINE`,
   `SERVICE_OR_MEETING`, `PAGE_HEADING` en `NOT_AN_OUTING`).
5. **Werkwijze.** Altijd eerst testen (`python -m pytest tests/v2`), dan een pull request met uitleg
   in gewone taal. Claude voegt die pull request daarna zelf samen (afspraak met de eigenaar van
   13 oktober 2026), maar alleen als de tests slagen en, bij een verandering aan het ophalen of
   indelen, een proef met de echte websites door de keuring komt. Vóór het samenvoegen kijkt een
   aparte hulpagent zonder voorkennis van het werk de wijziging na (een frisse blik vindt wat de maker
   mist, zoals echte uitjes die een nieuwe regel ten onrechte weghaalt); wat die vindt wordt eerst
   opgelost. Daarna meldt Claude in gewone taal wat er is veranderd.

## Hoe de motor werkt (kort)

1. `collector/discover_venues.py`: zoekt nieuwe websites via OpenStreetMap (podia, dorpshuizen,
   musea, cafés, verenigingen, gemeentehuizen, en dorpen met een eigen website) en Wikidata
   (festivals, dorpen en gemeenten), plus de tips in `collector/tips.json` en de gevonden
   dorpswebsites (`data/source_candidates.json`). OpenStreetMap en Wikidata vraagt hij eens per week
   (meteen bij een nieuw werkgebied, en altijd als de motor met de hand start; `data/zoekronde.json`).
   OpenStreetMap per provincie, met reserveservers; Wikidata met gewone SPARQL en QLever als reserve.
   Lukt een zoekvraag niet (de servers zijn vaak druk), dan probeert de volgende ronde het opnieuw.
   `collector/village_sites.py` loopt elke plaats in het werkgebied na (eens per drie maanden): het
   probeert veelgebruikte websitenamen (eenrum.nl, dorpsbelangeneenrum.nl, ...), kijkt (met respect
   voor robots.txt) of de site echt bij die plaats hoort, en bewaart het oordeel in
   `data/dorpssites.json` ('dorpssite', 'twijfel' of 'nee', altijd met een reden). Alleen
   'dorpssite' gaat vanzelf de wachtrij in; twijfelgevallen eerst nakijken (dan als tip toevoegen).
2. `collector/source_probe.py`: test of een website een leesbare agenda heeft (ook via de link
   naar de agenda op de voorpagina; een agenda mag een lijst, kaartjes of een tabel met kopjes als
   'Datum | Tijd | Activiteit' zijn). Volgorde: tips, nieuwe dorpswebsites, websites die een oudere
   test afwees, nieuwe websites van gemeenten en festivals (Wikidata), andere nieuwe websites, dan
   herkansingen na een wachttijd. Geen robots.txt betekent: welkom. Een kapot certificaat: dan via
   http. Een storing: de volgende dag opnieuw. Verhuisd naar een andere website: status 'moved' met
   het nieuwe adres erbij (`probeDetails.movedTo`); niet vanzelf volgen (het kan een verkocht domein
   zijn), maar nakijken en een goed nieuw adres als tip toevoegen. Weigert een website de motor
   (403), dan respecteren we dat.
3. `collector/auto_activate.py`: zet geschikte bronnen aan in `collector/web_crawl_sources.json`.
   Een dorpswebsite krijgt de plaats van het dorp mee, voor uitjes zonder eigen plaats.
   Laadt een grote zaal zijn programma met JavaScript, maar staat het als gegevens (JSON) op de eigen
   website, dan kan de bron met de hand worden ingesteld met `extractorHint: "json_api"`
   (`collector/json_api_events.py`; voorbeeld: Atlas Theater). Zet het genre van de organisator om
   naar schema.org (`genres`): dat gaat bij het indelen voor de rubriek in de link.
4. `pipeline/stage_active_sources.py` + `pipeline/build_auto_events.py`: halen de agenda's op
   en schrijven `data/auto_events.json`. Na 35 minuten rondt de motor af met wat er is; een bron
   die niet af kwam, storing had of niet te lezen was (website even plat), houdt zijn uitjes van de
   vorige keer. Elke agenda wordt hooguit om de zes uur opgehaald (`data/opgehaald.json`), zodat
   kleine websites niet elke ronde bezoek krijgen; daartussen blijven de uitjes van de vorige keer
   staan. Met de hand gestart haalt de motor alles op.
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
   De Duitse of Engelse versie van een uitje naast de Nederlandse ('/de/agenda/') valt weg, net als
   tekst voor schermlezers in de naam ('(opent bij de bron)'), een dubbele naam en een begintijd van
   00:00 (dat is 'tijd onbekend'). Een link die eigenlijk een e-mailadres is, telt niet als link.
   Eén kapot uitje laat de fabriek niet vastlopen (het staat in `status.json` onder `onleesbaar`).
   Een bron bewust uitzetten: `"enabled": false` met `disabledReason` in de bronnenlijst (een
   nieuwssite ook op de uitsluitlijst); de keuring weet dan dat die uitjes mogen verdwijnen.

## Ontbreekt er een uitje?

- Staat het op de eigen website van een organisator, dorp of gemeente? Zet die website in
  `collector/tips.json` (met `naam`, `reden`, `datum` en `plaats`); de motor test hem de volgende ronde
  als eerste. Staat het programma op een losse pagina (zoals de Zuidlaardermarkt bij de gemeente
  Tynaarlo), zet dan die pagina als tip.
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
