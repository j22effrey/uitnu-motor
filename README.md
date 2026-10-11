# UITNU motor

De motor achter [UITNU](https://uitnu.pages.dev): de uitagenda voor Groningen en omgeving.

Elke nacht draait deze repo vanzelf:

1. **Bronnen zoeken.** Elke maandag zoekt hij nieuwe plekken en festivals met een eigen website, via OpenStreetMap (ODbL) en Wikidata (CC0).
2. **Bronnen testen.** Per ronde test hij 120 websites op een agenda die een robot kan lezen: schema.org, iCal, WordPress-agenda's of een gewone agendapagina.
3. **Bronnen aanzetten.** Bronnen die aan alle eisen voldoen, gaan automatisch aan: robots.txt staat het toe, ze liggen binnen 60 km van Groningen, en het is geen verzamelsite of social media.
4. **Agenda's ophalen** bij alle actieve bronnen.
5. **Keuren.** Komt er te weinig binnen, valt een bron ineens weg of klopt er iets niet, dan blijft de vorige agenda staan.
6. **Publiceren.** De agenda komt in `data/v2/events.json`, en de site laat zich opnieuw bouwen.

UITNU haalt uitjes rechtstreeks bij organisatoren, podia, musea, dorpshuizen en gemeenten. We nemen alleen feiten over: naam, datum, tijd, plek en een link. Andere uitagenda's en verzamelsites gebruiken we niet als bron.

Organisator en wil je niet dat UITNU je agenda leest? Zet een regel voor `UITNU` in je robots.txt, of laat het ons weten via https://uitnu.pages.dev/contact/.
