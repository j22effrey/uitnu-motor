"""Eén indeling voor heel UITNU.

Regels, in deze volgorde:
1. handmatige correctie (overrides.json): per uitje of op naam, altijd met een reden;
2. trefwoorden in titel en beschrijving, met vaste uitzonderingen;
3. wat de organisator zelf op de pagina van het uitje zet (soort volgens schema.org, trefwoorden),
   of de rubriek waarin hij het zet (de map in de link, zoals '/cursusprogramma/');
4. een regel per locatie of bron (website van een podium);
5. de oude categorie van de bron als hint;
6. anders 'overig'.

Festival: alleen als het echt een festival is (vaste regel 3): een groot terrein of meerdere zalen,
meerdere podia en vooral verschillende artiesten. Een naam met 'festival' is daar geen bewijs voor.
Bewijs is: de organisator noemt meerdere podia, een line-up of een festivalterrein, of het staat
in het festivalregister (overrides.json, 'namen', met reden).

Indelen labelt alleen: deze module laat nooit een evenement weg. Alleen not_an_outing() zegt
of iets helemaal geen uitje is (een gewone kerkdienst, een bestuursvergadering, de 50-plusclub);
dat beslist de fabriek.
Elke uitkomst bevat methode, reden en zekerheid, zodat fouten na te speuren zijn.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable
from urllib.parse import urlparse

from .kinds import DISCIPLINE_HINTS, KINDS, LEGACY_HINTS, SCHEMA_KIND_HINTS


def normalize(text: str) -> str:
    """Kleine letters, zonder accenten en met enkele spaties."""
    text = unicodedata.normalize("NFKD", (text or "").replace("\u00ad", ""))  # zonder zachte afbreekstreepjes
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _compile(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


# Trefwoorden per soort. Nederlandse samenstellingen ("stadswandeling") zijn de reden
# dat sommige patronen bewust zonder woordgrens aan het begin werken.
PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "film": _compile([r"\bfilm", r"bioscoop", r"cinema", r"filmhuis", r"documentaire", r"cinekid",
                      r"\((?:19|20)\d\d\)\s*$"]),   # 'L'Histoire de Souleymane (2024)': een film met jaartal
    "sport": _compile([
        r"hardloop", r"(?<!ver)(?<!door)(?<!aan)(?<!uit)loop\b", r"run\b", r"\btrail", r"toertocht", r"\d+\s?(km|kilometer|mijl)\b", r"\bmijl\b", r"marathon",
        r"triatlon", r"wedstrijd", r"toernooi", r"regatta", r"roeiwedstrijd", r"schaats",
        r"wielren", r"mountainbike", r"\bmtb\b", r"voetbal", r"korfbal", r"handbal", r"hockey",
        r"zwemtocht", r"sportdag", r"\brace\b", r"obstacle", r"gymnastiek", r"biljart", r"\bsjoel", r"koersbal", r"jeu de boules", r"gym",
        r"valpreventie", r"bewegen", r"\byoga", r"pilates", r"zumba", r"volleybal", r"badminton", r"tafeltennis",
        r"schietclub", r"klootschiet", r"\bdart", r"lasergam", r"bowl", r"fitness", r"kampioen",
        # een wedstrijd: 'Westerlee 1 - VVS 1' of 'Covos DS1 – VC Sneek DS2', of een sportclub (SV, VV, SC, FC)
        r"^(?:beker:? )?[\w .'/&-]+ (?:[dhj]s ?)?\d+ [-–] [\w .'/&-]+ (?:[dhj]s ?)?\d+\b", r"\b(?:sv|vv|sc|fc)\b",
        r"toernoai", r"toenooi", r"blijart", r"picklebal", r"kickboks", r"loopgroep", r"stoelfit", r"\bracing\b",
        r"\btt assen\b", r"skutsje", r"zeilwedstrijd", r"\bdammen\b", r"damclub",
        r"\bdraf(?:sport|koers|race)", r"harddraverij", r"kaatsen", r"\bkaats", r"fierljep", r"\bspeedway\b", r"autocross",
        r"\bisu\b", r"allround", r"\b[ewn]k (?:allround|sprint|afstanden|schaatsen|wielrennen|voetbal|zwemmen)",
    ]),
    "natuur": _compile([
        r"wandel", r"excursie", r"natuur", r"vogel", r"sterren", r"paddenstoel", r"wildpluk",
        r"kwelder", r"wadlo", r"boswachter", r"fietstocht", r"struin", r"nacht van de nacht",
        r"huifkar", r"landgoed", r"vaartocht", r"zwerftocht", r"rondvaart", r"nationaal park",
        r"kuier", r"pelgrim", r"zwerfvuil", r"opschoon", r"landschapsbeheer", r"bloembollen", r"himmeldei",
        r"(?:fiets|wandel|avond) ?(?:\d|vier)?-?daagse", r"snoei", r"houtdag", r"snoekfiskje", r"\bvissen\b",
    ]),
    "eten": _compile([
        r"culinair", r"food", r"proeverij", r"\bproeven\b", r"\bwijn", r"\bbier(?!run)", r"smaak",
        r"high tea", r"brunch", r"\bdiner\b", r"barbecue", r"\bbbq\b", r"kookworkshop",
        r"whisk(e)?y", r"cocktail", r"\bgin\b", r"(samen|gezamenlijk) eten", r"aan de kook", r"stamppot",
        r"maaltijd", r"\bkoffie(?!concert)", r"\blunch", r"vrijmibo", r"borrel", r"frietavond", r"visje eten",
        r"eetcaf", r"kookclub", r"lunch", r"\beten\b", r"jenever", r"etentje", r"diner\b", r"eetclub", r"snert", r"pannenkoek",
        r"italiaanse avond", r"bakkie", r"bakje", r"\bkoken\b", r"\bite\b", r"(?:dorps|buurt|aanschuif|samen) ?tafel\b",
        r"buffet", r"\bbakt\b", r"bakwedstrijd", r"aan (?:tafel|toavel)\b", r"\bkookt\b",
        r"\bsoep", r"(?:vrijdag ?)?(?:middag|avond) ?caf",
    ]),
    "markt": _compile([
        r"markt", r"(?<=\w)maart\b", r"braderie", r"beurs", r"fair\b", r"\bsalon\b|(?:woon|bruids|beauty|wellness|auto|boten|reis|vakantie)salon\b",
        r"reis ?event", r"reizen\b.*\bevent", r"rommel", r"vlooien", r"snuffel", r"krystmerk", r"\bmerke\b", r"\w+ruil\b", r"ruilbeurs", r"modelbouw",
        r"bazaa?r\b", r"kerstbo[oa]mverkoop",
    ]),
    "feest": _compile([
        r"kermis", r"feest", r"koningsdag", r"koningsnacht", r"sinterklaas", r"intocht",
        r"carnaval", r"optocht", r"lampion", r"halloween", r"spooktocht", r"lichtjes",
        r"vuurwerk", r"oud en nieuw", r"line ?dance", r"volksdans", r"\bquiz", r"gezellige avond", r"gesellige jun",
        r"oktoberfest", r"oktofest", r"nieuwjaarsduik", r"bingo", r"spellen", r"spelletjes",
        r"klaverjas", r"^kaarten\b", r"kaarten ?(?:avond|middag)", r"kaartclub", r"rummi", r"\bbridge\b", r"quiz", r"sint[ -]maarten", r"\bdisco",
        r"dans(middag|avond|feest|club)", r"trick or treat", r"spokentocht", r"ladies ?night", r"happy hour",
        r"hollandse avond", r"hitster", r"pijltjes gooien", r"kerstmiddag", r"\bsint\b", r"klozum", r"carnaval",
        r"nieuwjaars ?(receptie|visite|bijeenkomst)", r"spookhuis", r"\bgala\b", r"paasvuur", r"vreugdevuur",
        r"jubileum(?!\w*concert)", r"neut\W?e?n schait\W?e?n", r"noten schieten", r"puzzel", r"bordspel",
        r"paasmiddag", r"bridgedrive", r"\bforro\b",
    ]),
    "theater": _compile([
        r"theater", r"voorstelling", r"toneel", r"cabaret", r"comedy", r"stand-?up",
        r"musical", r"\bopera\b", r"ballet", r"\bdans(voorstelling|theater)?\b",
        r"poppen(kast|theater)", r"circus", r"teater", r"komeedzje", r"komedie", r"klucht",
    ]),
    "muziek": _compile([
        r"concert", r"\blive\b", r"band\b", r"\bkoor", r"koren", r"orkest", r"\bdj\b", r"optreden",
        r"gospel", r"fanfare", r"shanty", r"smartlap",
        r"clubnacht", r"\bparty\b", r"\bjazz", r"\bpop\b", r"\brock", r"\bblues", r"\bmetal\b",
        r"hip-?hop", r"techno", r"\bhouse\b", r"recital", r"\borgel", r"cantate", r"muziek",
        r"singer-?songwriter", r"\brave\b", r"taptoe", r"\btrio\b", r"kwartet", r"kwintet", r"\bensemble\b",
        r"worship", r"\bmusic\b", r"jam ?sessie", r"zang", r"zingen", r"ensemble", r"piano", r"pop\b", r"draaiorgel",
        r"\bwinds\b", r"\bbazuin\b", r"brass ?band", r"blaasorkest", r"\w+koor\b", r"tribute",
        r"huiskamer(?:podium|concert)", r"accordeon", r"blokfluit", r"cellist", r"\bcello", r"fagot",
        r"saxofo", r"klarinet", r"violist", r"\bviool", r"gitarist", r"harpist", r"trompet", r"fluitist", r"pianist",
        r"\bzingt\b", r"cantorij", r"evensong",
    ]),
    "kunst": _compile([
        r"tentoonstelling", r"expositie", r"\bexpo\b", r"museum", r"galerie", r"\bkunst",
        r"atelier", r"monument", r"erfgoed", r"open kerk", r"kerkpad", r"rondleiding", r"beelden van",
        r"beeldhouw", r"historisch", r"archeolog", r"cultuur", r"geschiedenis", r"herdenking", r"schilderij",
    ]),
    "lezing": _compile([
        r"lezing", r"workshop", r"cursus", r"masterclass", r"\bdebat\b",
        r"symposium", r"voorlees", r"\bcollege\b", r"leerhuis", r"gespreksgroep", r"meditatie",
        r"repair ?caf", r"bloemschik", r"verkeersregels", r"creatief caf", r"handwerk", r"informatie ?avond",
        r"\bbrei(?:en|werk|cafe|club|middag|avond|ochtend|les)\b", r"\bhaak", r"\bcrea\b", r"digitaal ?huis", r"literatuur", r"leesclub", r"boekenclub", r"verhalen", r"doe-? ?middag", r"thema ?avond", r"webinar",
        r"presentatie", r"werksessie", r"dorpsvisie", r"omgevingsvisie",
        r"info ?avond", r"reparatie", r"hartveilig", r"reanimatie", r"\baed\b", r"\behbo\b", r"kerststuk",
        r"\binformatie\b", r"aan het woord", r"voorlichting", r"klankschaal", r"retraite", r"retreat",
        r"fotograferen", r"sierlijk schrijven", r"kalligraf", r"voorlez", r"veurlez", r"tekenen en schilderen",
        r"(?:long|post)[ -]?covid",
        # thema-cafés: een praatavond of uitleg, geen café
        r"(?:taal|alzheimer|dementie|vrouwen|filosofisch|praat|kennis|rouw|mantelzorg|boeken|lees|klimaat|energie|geheugen) ?caf",
    ]),
    # Uitjes die vooral om kinderen draaien. Een voorstelling of concert voor kinderen blijft
    # theater of muziek, met het label 'Voor kinderen'.
    "kinderen": _compile([
        r"springkussen", r"kinderboerderij", r"kinder(feest|disco|middag|activiteit|maand|speel|dag)",
        r"\bkids?(club|dag|feest|middag)?\b", r"knutsel", r"schmink", r"\bpeuter", r"\bkleuter",
        r"speeltuin", r"ballonnen", r"klimpark", r"indoor ?speel", r"speel ?(je mee ?)?(ochtend|middag)",
        r"paasei", r"knustel", r"\bkamp\b", r"^jongeren\b", r"pompoen",
        r"jeugd ?soos", r"tiener ?soos", r"(?:foar|voor) de jeugd", r"sprookjes(?:tocht|wandeling|route|speurtocht)",
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
                           r"|gemeenteavond|\w*gearkomste|redactievergadering"
                           # mededelingen voor het dorp, geen uitje
                           r"|oud ?papier|collecte\w*|kopij|wintertijd|zomertijd|\w*afval|container|\w*spreekuur"
                           # zaalverhuur en vaste clubavonden in de agenda van een dorpshuis
                           r"|verhuur|zaalhuur|bezet|gereserveerd|onderhoud|schoonmaak\w*|\w*overleg|(?<!open )(?<!openbare )(?<!generale )repetitie\w*"
                           r"|oefenavond|trainingsavond|contactavond|vrouwenvereniging|vrouwen van nu|afdelingsavond"
                           r"|ledenavond|(?:advents?|paas|pinkster)dienst|doorzichtige zak|papier en karton"
                           r"|verantwoord alcohol schenken|\w*vergadering\w*|(?<!open )(?<!openbare )(?<!generale )(?<!\w)\w*repetitie|\bnieuws\b|voorzitter"
                           r"|\bverkeer\b|wegafsluiting|wegwerkzaamheden|wintertied|dagelijks bestuur|\w*dagsbestuur|^bestuur"
                           r"|bestuursoverleg|\w*dienst in de \w*kerk|dankdienst|dankdag voor gewas|\w*actie\b"
                           r"|black friday|schoen(tje)? (zetten|ophalen)|kerst[\w-]*dienst|jantje beton"
                           r"|uitnodiging volgt|aanvragen|\boptie\b|donateur\w*|noodsteunpunt|\w*aksje|nl[ -]?doet"
                           r"|vrouwen van deze tijd|(?:ouderen|senioren|bejaarden) ?soos|gebiedsregisseur|wijkagent|dorpscoach"
                           # kerk en club voor leden: kerkenraad, weeksluiting, interne schaakrondes, KNVB-bijeenkomsten
                           r"|kerkenraad|weeksluiting|dienst$|(?:interne|externe) ronde|^knvb|start fase \d"
                           r"|bijeenkomst (?:van het )?bestuur|\w*vaccinat\w*|\d+ (?:jaar|jier) (?:getrouwd|troud)"
                           r"|ald ?papier|\w*(?:container|kontainer)\w*|vrijwil\w*gers\w*"
                           # een mededeling of lege aankondiging: 'gesloten voor publiek', 'nadere info volgt'
                           r"|gesloten|nadere info\w* volgt"
                           # vergaderingen en bijeenkomsten voor leden of vrijwilligers: niet voor publiek
                           r"|ledenvergadering|jaarvergadering|bestuursvergadering|alv|vrijwilligers\w*|frijwilligers\w*|besloten"
                           # mededelingen: iets is dicht (de huisartsenpraktijk, de bibliotheek)
                           r"|(?:\w*praktijk|apotheek|bibliotheek|balie|kantoor|winkel|dorpshuis|kerk) (?:is )?gesloten"
                           # afgelast of alleen een mededeling: 'GAAT NIET DOOR', 'GEEN frietavond', de inleverdatum van
                           # het dorpskrantje, de milieubus, verkiezingen, wegwerkzaamheden, een verkoop
                           r"|gaat niet door|geannuleerd|afgelast|vervalt|^geen \w*(?:avond|middag|ochtend)|\w*inleverdatum"
                           r"|deadline (?:voor |kopij|inleveren|aanmelden|\w*(?:praet|krant|blad|bode|nieuws))"
                           r"|info volgt|milieubus|sortibak|grofvuil|grof (?:tuin)?a?f?val|ophaaldag|\w*verkiezingen|stembureau"
                           r"|\w*lidmaatschap|geef (?:jouw|je|uw) [\w ]{3,30} door|wedstrijdoverzicht|wedstrijdprogramma"
                           r"|rehabilitatie|herinrichting|riolering"
                           r"|(?:kerstbomen|kerstboom|oliebollen|snert|appelflappen|loten|plantjes|bloembollen|bloemen|boeken|taarten)verkoop"
                           r"|overleden dierbare|zangseizoen"
                           # een kerkdienst onder een andere naam ('Samenzangdienst', 'Grunneger Dainst', 'Dienst in het MFC');
                           # (een act als 'Plafonddienst' op Explore the North blijft staan)
                           r"|(?:samenzang|zang|thema|jeugd|gezins|kinder|tiener|jongeren|doop|belijdenis|bevestigings"
                           r"|herdenkings|gedachtenis|oogst|bid|vesper|vroeg|oecumenische|openlucht|tent|muziek|lied|zegen|gospel"
                           r"|kerk|sing-?in|startzondag|start|oude?jaars?|nieuwjaars|avondmaals?|heilig avondmaal)dienst"
                           r"|\w*dainst|\w*tsjinst|^dienst"
                           # liturgie en retraites (ronde van 15 oktober): ook met muziek een dienst, geen uitje
                           r"|cantatedienst|choral evensong|evensong|kerstwijding|\w*-?sesshin|zen ?weekend|cursus in wonderen"
                           r"|avond over sutta\w*|huwelijksdag|^doperse dis(?!.*benefiet)"
                           # mededelingen: 'LeukeSpulletjes is geopend', 'Bekendmaking geboorte', 'Program wurdt noch ynfolt'
                           r"|^bekendmaking\w*|nieuw speeltoestel|is het (?:moeder|vader)dag|wurdt noch"
                           r"|noch ynfolt|nieuwjaarskaarten"
                           # circuitdagen voor betalende rijders, niets voor publiek
                           r"|puredriving|cool driving|rensportschool|^rsz autosport|^lotus club"
                           # een dienst onder de naam van de voorganger ('Ds. R. Sietsma', 'Br. K. Braam'), een dag van
                           # het kerkelijk jaar ('29e Zondag door het jaar', '2e advent', 'Dankdag') en gebeden
                           r"|^(?:ds|br|zr|prop|kand)\.? (?:[a-z]\.){1,3} ?[a-z]+|^(?:ds|pastor|pastoor|kapelaan)\.? [a-z]+"
                           r"|\d+e zondag (?:door het jaar|van de advent|na pinksteren|na trinitatis|van pasen|van de veertigdagentijd)"
                           r"|^(?:\d+e|eerste|tweede|derde|vierde) advent$|^dank ?dag\b|^biddag\b|^kerstavond$|^oudejaarsavond$"
                           r"|^allerzielen\b|^allerheiligen\b|\bf?vesper\b|\bfesper\b|taize ?gebed|\w+gebed\b|\bnoen$"
                           r"|(?:verdiepings|gespreks|bijbel|gebeds|studie)kring|kindernevendienst|zondagsschool|catechisatie"
                           # een sportclub: de kantinedienst, de pagina van een team ('S.C. Erica 1', 'VV Gieten 2 programma')
                           r"|kantine ?dienst\w*|^(?:s\.?c\.?|v\.?v\.?|s\.?v\.?|c\.?v\.?v\.?|f\.?c\.?|h\.?c\.?|v\.?c\.?) [\w .'-]+ \d{1,2}(?: programma)?$)\b")
# Knoppen en kopjes van een website die als naam van een uitje zijn meegekomen.
NOT_A_TITLE = re.compile(r"^(?:start|begin|aanvang|selecteer (?:een )?(?:tijdstip|datum|dag)|kies (?:een )?(?:tijdstip|datum|dag)"
                         r"|(?:bestel|koop) (?:nu )?(?:je |jullie |uw )?(?:tickets?|kaartjes?|kaarten)(?: .*)?|tickets?|meer info(?:rmatie)?|lees meer|bekijk"
                         r"|reserveren|aanmelden|inschrijven|start ?datum|eind ?datum|datum|plaats|locatie"
                         r"|(?:grote|kleine) zaal|zaal \d+|overige speeldata|volgende data|komende|praktische info"
                         r"|laatste nieuws|zet (?:het )?alvast in (?:uw|je) agenda|a ?genda|admin|aankomende (?:activiteiten|evenementen|gebeurtenissen|diensten)"
                         r"|even(?:emen)?t ?type(?: \w+)?|a ?ctiviteiten(?: \w+)?"
                         r"|informatie|tijd en(?: locatie)?|dorpsagenda|evenementgegevens|breng je evenement onder de aandacht"
                         # rubrieken van een agenda (Events Manager) en een tijdvak zonder naam
                         r"|(?:algemeen|activiteiten|activiteitencommissie|culturele commissie)(?:, .*)?"
                         r"|\d{1,2}[:.]\d{2}\s*(?:-|–|tot)\s*\d{1,2}[:.]\d{2}"
                         r"|kerst|dorpshuis|groen|oranje|(?:eerste|tweede|nulste|1e|2e|1ste|2de) kerstdag|goede vrijdag"
                         # een (tijd en) adres: dat is de plek, niet de naam
                         r"|(?:\d{1,2}[:.]\d{2} )?.*\b[a-z]+(?:straat|weg|laan|plein|dijk|pad|singel|kade|dreef|steeg) \d+\w?"
                         r"|(?:eerste |tweede |1e |2e |1ste |2de |de )?(?:paas|pinkster)dag|hemelvaart(?:sdag)?|bevrijdingsdag|nieuwjaarsdag|(?:kerst|herfst|voorjaars|mei|zomer)vakantie(?: regio \w+)?)"
                         r"(?: 20\d\d)?(?:\s*[(-].*)?$")
# Kopjes en knoppen van een website (de galerij, sponsors, contact, een losse datum): de hele titel is
# het kopje, er staat niets achter (anders blijft het staan: 'Programma-avond met lezing').
PAGE_HEADING = re.compile(r"^(?:fotogalerij|sfeerimpressie|kom in contact|contact|mede mogelijk gemaakt door|sponsoren gezocht"
                          r"|over ons|over (?:de|het) (?:stichting|vereniging|organisatie|festival)\b.*|over (?:dit|het|deze) (?:evenement|activiteit)|\w*club seizoen\b.*|pagina'?s|ontdek"
                          r"|wat is er (?:allemaal )?te beleven|het programma|programma|over deze film|thank you|bedankt|blok \d+|sign-?up"
                          r"|uitslag\w*\b.*|rabo clubsupport\b.*|details?"
                          r"|\d{1,2} (?:jan|feb|maa|mrt|apr|mei|jun|jul|aug|sep|okt|oct|nov|dec)[a-z]*(?: 20\d\d)?"
                          # het menu van een website ('Privacybeleid', 'Filteren', 'Je hebt het einde bereikt!')
                          r"|privacy\w*|cookie\w*|disclaimer|algemene voorwaarden|filter(?:en)?|zoeken|(?:je hebt )?het einde bereikt"
                          r"|contact ?informatie|contactgegevens|diensten ?menus?|educatie|specials|nieuwsbrief|vacatures?|webshop"
                          r"|cadeaubon\w*|toegankelijkheid|bereikbaarheid|route(?:beschrijving)?|parkeren|openingstijden"
                          r"|veelgestelde vragen|faq|inloggen|login|mijn account|winkelwagen|prikbord|vandaag in de stad"
                          r"|(?:see )?(?:our )?gallery|galerij|over deze (?:film|voorstelling|show|tentoonstelling|expositie|activiteit)"
                          r"|volgeboekt|uitverkocht|\d+ (?:t/m|-) \d+ van \d+ resultaten|evenementbeschrijving"
                          r"|tijdstip|deel activiteit|terugkerende activiteit|eigenschappen|all dates|bestel|recente berichten"
                          r"|upcoming evenementen|volgende activiteit|wedstrijden|bekendmakingen|vergaderagenda|algemene agenda"
                          r"|plaza \d+|deuren open [\d:., ]+(?:,? ?aanvang [\d:.]+)?|programma(?: 20\d\d| gehele programma)|agenda(?: \d{1,2} \w+| de \w+)|knmv"
                          r"|voetbal|padel|buurthuus|documentaire|.* informatie bestel"
                          # een maand als kopje ('October 2026', 'Januari')
                          r"|(?:januari|februari|maart|april|juni|juli|augustus|september|oktober|november|december"
                          r"|january|february|march|june|july|august|october)(?: 20\d\d)?)\W*$")
# Een titel die alleen een club of vaste ontmoeting noemt (de 50-plusclub, dorpsbelangen, de inloop):
# een bijeenkomst voor leden of een vaste koffieochtend, geen uitje. Staat er een activiteit bij
# ('Dansavond 50 plus', 'Dorpsbelangen nieuwjaarsreceptie', 'Inloopmiddag met lezing'), dan blijft het staan.
CLUB_ONLY = re.compile(r"^\w*\d0 ?-?(?:plus|\+)(?: ?(?:club|soos|societeit|middag|ochtend|gezellige middag|bijeenkomst))?$"
                       r"|^(?:vereniging )?(?:dorps|doarps)belang(?:en)?(?: \w+)?$|^plaatselijk (?:belang|comite)(?: \w+)*$"
                       r"|^inloop ?(?:ochtend|middag|avond|uur)?$|^(?:de )?(?:huiskamer|doarpskeamer|dorpskamer)$"
                       r"|^vrouwen van [\w-]+$|^(?:stichting )?ouderen [\w -]+$|^vriendenkring [\w -]+$|^buurtvereniging [\w -]+$")
# Seks- en naaktfeesten en andere uitjes alleen voor volwassenen: nooit in een agenda voor iedereen,
# van welke bron ook. (Let op: 'Sexbierum' is een dorp, dus 'sex' alleen als los woord.)
ADULT_ONLY = re.compile(r"\bnaakt\b|\bnaked\b|\bmen only\b|\bt-?girl|\berot|\bsex\b|\bsexy\b|\bseks\b|swinger"
                        r"|\bfetish|\bbdsm\b|\bporn|\bxxx\b|\badults? only\b|\b18\+ ?(?:party|feest)|darkroom"
                        r"|gay ?sauna|\bsauna ?party|\bcruising\b|strip ?club|striptease(?! van de dood)|peepshow|\bkinky\b|\bfkk\b|\bnudis"
                        r"|thunder from down under|chippendales|\bmale revue\b|mannenstrip")
# Niet voor het grote publiek (vraag van de eigenaar, 13 oktober): de vaste les of oefenavond van een
# club of groep ('Koor', 'Fanfare Swettewyn', 'Wandelgroep Wommels', 'Yoga', 'Koffieochtend'), een
# competitiewedstrijd van amateurteams ('Covos DS1 – VC Sneek DS2'), en wat alleen voor leden of
# dorpsbewoners is. Staat er iets openbaars bij ('Concert', 'Toernooi', 'Open dag'), dan blijft het staan.
CLUB_SESSION = re.compile(
    r"^(?:(?:ying|yin|hatha|stoel|zwangerschaps|senioren) ?)?yoga|^pilates|^zumba|^fitness|^bootcamp|^spinning"
    r"|^aquarobics|^(?:senioren|ouderen|stoel) ?(?:gym|fit|yoga)|^stoelfit|^gym\b|^badminton|^tafeltennis|^volleybal"
    r"|^basketbal|^kickboks\w*|^boksen|^judo|^karate|^taekwondo|^picklebal\w*|^pickleball|^koersbal|^jeu de boules"
    r"|^petanque|^biljart(?:en)?\b|^biljart- en kaartsoos|^sjoelen|^dammen|^schaken|^bridge\b(?! over\b)|^bridgeclub"
    r"|^klaverjas(?:sen|kompetitie|competitie|avond)?\b|^kaarten\b|^kaartclub|^rummikub|^spelletjes ?(?:middag|avond)"
    r"|^spellen ?(?:middag|avond)|^koffie ?(?:ochtend|inloop|uurtje|drinken|middag)|^(?:vrijdag ?)?(?:middag|avond) ?caf[eé]"
    r"|^samen eten\b|^eetclub|^breiclub|^haakclub|^handwerk(?:club|en)\b|^naaiclub|^creaclub|^crea ?(?:avond|middag|ochtend)"
    r"|^(?:muziek|gitaar|piano|zang|dans|teken|schilder)les\b|^(?:kinder|jeugd|gemengd |mannen|vrouwen|shanty|sjong)?ko(?:o|a)r\b"
    r"|^fanfare\b|^brass ?band\b|^muziekvereniging|^harmonie\b|^wandel ?(?:club|groep)|^wandel je fit|^kuier ?(?:klub|groep)"
    r"|^(?:hard)?loop ?groep|^fiets ?(?:club|groep)|^(?:jeugd|tiener|ouderen|senioren)? ?soos\b|^peuter ?(?:mee)?speel\w*"
    r"|^speel je mee \w+|^stut en steun|^repetitie|^oefen(?:avond|ochtend)|^training\b|^jeugdtraining"
    r"|^(?:een |dorps)?bakkie\b|^kookclub|^bingo(?:avond|middag)?$|^(?:thuis|uit)wedstrijd\b"
    r"|^(?:ochtend ?)?koffie ?leut|^(?:de )?(?!(?:blues|jazz|folk|comedy|film|pop|muziek|swing)club)\w+club\b|^leesclub|^(?:christelijke )?vrouwengroep|^\w*dansclub|^soos\w*|^inloop\b|^\w+inloop$"
    r"|^startgroep \d|^(?:knltb|knvb|nevobo|knbb|kndb|nhv)\b|^verenigingsavond|^\d0 ?\+? ?(?:gym\w*|fit\w*|yoga)"
    r"|^.*\btraining (?:[ojm]\d|jo\d|mo\d|jeugd|selectie)"
    # meditatie, een retraite of qigong: een vaste les of cursus, net als yoga
    r"|^.*\blichtcirkel|^mantra ?zingen|^klankschaal(?:beleving|meditatie)|^5 ?ritmes|^vrouw, lijf (?:&|en) stem"
    r"|^inloop(?:kwartier|moment|uur|ochtend|middag)\b|^peuter ?gym|^power yoga|^.*\byoga\b.*\bgevorderd|^.*\bgevorderd(?:en)?$|^beeldhouwen\b|^tekenen en schilderen$"
    r"|^.*\bmedit(?:atie|eren)\w*|^.*retr(?:aite|eat)|^.*\bqi ?gong\b|^.*\btai ?chi\b|^.*\bdeep relaxation\b")
# (Een kampioenschap van de club, zoals 'Klaverjassen (kampioenschap v. teams)', is voor de leden.)
PUBLIC_EVENT = re.compile(r"concert|uitvoering|optreden|voorstelling|toerno(?:o|a)i|toenooi|drive\b|open (?:dag|les|avond|huis|podium)"
                          r"|demonstratie|clinic|workshop|festival|jubileum|markt|expositie|tentoonstelling|\bshow\b|gala"
                          r"|feest|viering|proefles|kennismak|presentatie|lezing|actie|benefiet|\bquiz")
# Teamnummers zijn kort ('1', 'DS1', 'MA1', 'JO13-2'); een jaartal ('Boney M 1976') is geen team.
TEAM_MATCH = re.compile(r"^(?:beker:? )?[\w .'/&-]+ (?:[a-z]{1,2} ?|jo\d+-|mo\d+-)?\d{1,2} ?[-–] ?[\w .'/&-]+ "
                        r"(?:[a-z]{1,2} ?|jo\d+-|mo\d+-)?\d{1,2}\b")
# Een spel of sport van de club, ook midden in de naam ('Maatbiljarten Krekt Rekke', 'Darten in dorpshuis
# De Molenwiek'). Een toernooi, drive of prijsklaverjassen is open voor iedereen en blijft staan.
CLUB_GAME = re.compile(r"\w*biljart\w*|\bblijart\w*|\w*klaverjas\w*|^bridge(?:n|club)?\b(?! over\b)|\bbridge ?(?:club|avond|middag|les)\b"
                       r"|\bbridgen\b|\bsjoel\w*|^dammen\b|\bdam ?(?:club|avond|middag)\b|^schaken\b|\bschaak ?(?:club|avond|middag|les)\b"
                       r"|\bkoersbal\b|\bjeu de boules\b|\bdart(?:en|s)?\b|pijltjes gooien")
CLUB_GAME_PUBLIC = re.compile(PUBLIC_EVENT.pattern + r"|\bprijs\w+|\bopen\b|\b(?:nk|wk|ek)\b|grand prix|masters|\bcup\b"
                              r"|international|nederlands kampioenschap")
# Alleen voor de leden van een club, ook al heet het toernooi: de competitie, het clubkampioenschap,
# het slottoernooi van het seizoen, een bekerwedstrijd.
CLUB_INTERNAL = re.compile(r"\w*competitie\b|clubkampioenschap\w*|\bslot ?to(?:er|e)?n(?:oo|oa)i\b"
                           r"|\bsluitings-? ?to(?:er|e)?n(?:oo|oa)i\b|\bclub ?to(?:er|e)?n(?:oo|oa)i\b|\bonderlinge\b|bekerwedstrijd\w*")
# Niet noemenswaardig (vraag van de eigenaar, 14 oktober: 'stuk voor stuk niet noemenswaardig', zoals in
# Westerlee): wat een dorpshuis of buurtcentrum voor de eigen mensen doet. Koffie, soep of friet in het
# dorpshuis, een borrel, een dorpsmaaltijd, de dorpskamer, een handwerk- of taalcafé, de soos. Staat er iets
# bij dat wel een uitje is ('Koffieconcert', 'Borrel met live muziek', 'Dorpskamer: lezing'), dan blijft het staan.
VILLAGE_ROUTINE = re.compile(
    # vrijwilligers aan het werk en de eigen kantine ('Bouwploeg' in MFC Wjukken, 'Cafetaria verkoop' in Westerlee)
    r"^bouwploeg$|^cafetaria ?verkoop$|"
    r"\bkoffie ?(?:ochtend|inloop|uurtje|drinken|middag|moment|tafel|leut)|\bop de koffie\b|\bbakkie\b|\bbakje\b|buurtbakje"
    r"|\w*borrel\w*|\bvrij ?mi ?bo\b|\bsoep ?(?:uur|maaltijd|middag|ochtend)|\bstamppot ?(?:ochtend|middag|avond|eten)"
    r"|\bfriet ?avond|\bsnack ?(?:avond|bar)\b|\w*maaltijd\b|\bsamen (?:eten|koken|lunchen|tafelen)\b|running dinner"
    r"|\b(?:dorps|doarps|buurt|buur)(?:maaltijd|diner|etentje|eten|lunch|tafel|miel|iten)\b|\bopen tafel\b|\bstamtafel\b"
    r"|\bite\b|\w*(?:brunch|buffet)\b|\w*lunch(?:buffet)?\b"
    r"|dorpskamer|doarpskeamer|dorpshuiskamer|buurtkamer|\bhuiskamer\b|\w*handwerk\w*|\bbrei ?cafe|\bhaak ?cafe|\bcreatief cafe|\bcrea ?(?:cafe|doe)"
    r"|\b(?:vrouwen|mannen|internet|computer|digi|taal|mienskip) ?cafe\b|digi-? ?taalhuis|\btaalhuis\b|\w*soos\b"
    r"|\bhobby ?(?:club|lub|middag|avond)\b|\bontmoetings?(?:middag|ochtend|avond)\b|\bbewegen en ontmoeten\b"
    r"|\bcafe ?avond in (?:het )?(?:buurthuis|dorpshuis)|\bverrassingsmiddag\b"
    r"|positieve gezondheid"
    # Samen eten of koken in het dorp ('Visje eten', 'Mosselen eten', 'Turks koken', 'Koken met de Wegwijzer',
    # 'Keallepoat kafee', 'Spieksters aan toavel', 'Heel Spijk bakt'); een kookworkshop blijft staan.
    r"|^[\w'-]+ eten$|^eetcaf|\bkook(?:t|en) met\b|^(?:[\w-]+ )?koken\b(?!.*(?:workshop|masterclass|demonstratie|wedstrijd|kinder|kids))"
    r"|(?<!filosofysk )\bkafee\b|^heel \w+ bakt\b|\b(?:aan|oan) (?:tafel|toavel)\b(?!.*\bsint)|koningsontbijt"
    # Bingo in het dorp ('Bingo avond', 'Kinderbingo', 'Najaarsbingo van de Oranjevereniging'); een muziek- of dragbingo
    # in een club of café blijft staan.
    r"|^(?!.*\b(?:show|drag|loco|rave|party|fout|silent|quiz|disco|kroeg)\b).*\b\w*bingo\w*\b")
# In een dorpshuis, buurthuis of MFC is samen eten, bingo of een high tea iets voor de eigen mensen.
VILLAGE_HALL = re.compile(r"dorpshuis|dorpshus|dorpshoes|doarpshus|dorpshuus|buurthuis|buurthuus|buurtcentrum|wijkcentrum"
                          r"|\bmf[ac]\b|multifunctione|kantine|ontmoetingscentrum")
VILLAGE_HALL_ACTIVITY = re.compile(r"\beten\b|maaltijd|\bdiner\b|\bkoken\b|\bkookt\b|\bbingo\b|high ?tea|\bkoffie\b|\bsoep\b"
                                   r"|\bsnert\b|pannenkoek|\blunch|brunch|italiaanse avond|\bproeverij\b")
# Wat in een dorpshuis wel een uitje is: een proeverij van wijn, bier of whisky, iets voor kinderen of met de Sint.
VILLAGE_HALL_PUBLIC = re.compile(r"wijn|bier|whisk|\bgin\b|kinder|kids|\bsint\b|sinterklaas|piet|moord|mystery|race")
ROUTINE_PUBLIC = re.compile(PUBLIC_EVENT.pattern + r"|cabaret|theater|toneel|muziek|muzikale|\blive\b|\bband\b|\bdj\b|\bfilm"
                            r"|disco|dansavond|optocht|podium|jazz|blues")
# Hulp, zorg, cursussen, inspraak en school: nuttig, maar geen uitje. Repair café, mantelzorgcafé,
# valpreventie, een cursus computer of reanimatie, de dorpsvisie of een informatieavond, de open lessen
# van de basisschool, een reünie, een vriendendag voor donateurs, een nieuwjaarsreceptie.
# (Een concert, voorstelling, markt of tentoonstelling erbij blijft staan.)
SERVICE_OR_MEETING = re.compile(
    r"repair ?cafe|reparatie ?(?:cafe|balie)|kledingreparatie|herstel ?cafe|mantelzorg\w*|lotgenoten\w*|long ?covid|post-? ?covid"
    r"|alzheimer ?cafe|dementie ?cafe|\bautisme\b|parkinson ?cafe|\brouw ?(?:cafe|groep|verwerking)|valpreventie|\bik sta sterk\b"
    r"|\baed\b|reanimatie\w*|\behbo\b|\bbhv\b|verkeersregels|\bdigid\b|\bop de computer\b|veilige wachtwoorden"
    r"|\bcursus:? (?:computer|android|ipad|iphone|tablet|laptop|smartphone|fotoboek|foto'?s ordenen|verder werken)|\borde op je \w+"
    r"|dorpsvisie|omgevingsvisie|woningbouw\w*|\w*bouwplan\w*|schetsplan|conceptontwerp|werksessie|inspraak\w*|klankbord\w*"
    r"|informatie ?(?:avond|bijeenkomst|middag|ochtend)|\binfo ?(?:avond|bijeenkomst)\b|voorlichting\w*"
    r"|\benergie ?(?:delen|loket|coach\w*|cafe)\b|subsidie\w*|\bondernemers ?(?:avond|cafe|ontbijt)\b|\bnetwerk ?(?:borrel|bijeenkomst)\b"
    r"|\bnieuwjaars ?(?:receptie|bijeenkomst|visite|byienkomst)\b|basisschool\w*|\bopen lessen\b|\bouderavond\b|\w*reunie\w*"
    r"|vrienden ?dag|\bgroep \d(?: ?[-/] ?\d)?\b"
    r"|sociaal werker|inloopavond nieuwbouw|nieuwbouwplan\w*|\binloopavond\b|gemeente \w+ bijeenkomst|open call|schrijf ?ochtend|\bis (?:weer )?geopend$"
    # zorg in een zaal ('Bloedprikken Certe' in De Skans, 19 oktober 2026)
    r"|bloed ?prik\w*|\bprik ?post\w*|griep ?prik\w*|\bbloed ?afname")
SERVICE_PUBLIC = re.compile(r"concert|voorstelling|optreden|uitvoering|festival|expositie|tentoonstelling|markt|beurs|\bshow\b|musical"
                            r"|theater|toneel|cabaret|optocht")
MEMBERS_ONLY = re.compile(r"(?:alleen|enkel|uitsluitend) (?:voor )?(?:leden|bewoners|inwoners|dorpsbewoners|buurtbewoners|donateurs)"
                          r"|ledengearkomst|^buurtvereniging\b"
                          r"|voor (?:onze )?(?:leden|dorpsbewoners|buurtbewoners|bewoners van)\b|voor inwoners van|bewoners(?:avond|middag|bijeenkomst)"
                          r"|leden(?:middag|ochtend|dag|uitje|reis)|leden en donateurs"
                          # leden, studenten, cursisten (ronde van 15 oktober); geen uitzondering voor 'feest'
                          r"|\bvaarbewijs\b|rijlessen|diplomafeest|\binauguratie\b|beljatten|blousenfeest"
                          r"|^studiemiddag$|^kiezelweek|feestavond vrienden van|ynwenners\w*|trainerschap|fortbildung"
                          r"|cursusbijeenkomst\w*|\bjaargroep\b|\btrajecten\b|\bjota\b|beroepenfeest|career fair")
# Ook voor de leden, tenzij er iets openbaars bij staat ('Open les 1', 'Winterstop toernooi',
# 'Mikstoernooi VV Suameer' blijven staan).
MEMBERS_UNLESS_PUBLIC = re.compile(r"\bles \d+$|^(?:winter|zomer)stop\b|kaartavond|verenigingsavond"
                                   r"|\w*(?:party|feest|resepsje|famyljedei)\b.*\b(?:v\.?v\.?|s\.?v\.?|s\.?c\.?) [a-z]+$")
# Voor de ouderen van het dorp ('Kerstmiddag voor ouderen', 'Kerstlunch 50+'): niet voor het grote publiek.
# Een festival, beurs, toernooi of concert voor senioren blijft staan.
# Een leeftijdsgroep alleen ('Dansavond 50 plus') is geen reden: die is open voor iedereen van die leeftijd.
SENIORS_ONLY = re.compile(r"^ouderen\b|ouderen ?(?:middag|ochtend|lunch|diner|kerst|soos|reis|uitje)|(?:voor|met) (?:de )?ouderen"
                          r"|(?:lunch|diner|middag|ochtend|kerst\w*) [56][05] ?(?:\+|plus)|[56][05] ?(?:\+|plus) ?(?:club|soos|middag|ochtend|lunch)"
                          r"|senioren ?(?:middag|ochtend|soos|reis|kerst|lunch)|^\w+ ouderen$"
                          r"|\b[5-7][05] ?(?:\+|plus) ?(?:actief|club|soos|groep|vereniging|middag|ochtend|lunch)"
                          r"|\balderein\b|\baldere(?:n|minsken)\b")
SENIORS_PUBLIC = re.compile(r"festival|beurs|toerno(?:o|a)i|concert|markt|voorstelling")
# Alleen de winkels open ('Koopzondag'): geen uitje. Met iets erbij ('Koopzondag en straatheater') wel.
SHOPS_ONLY = re.compile(r"\bkoop(?:zondag|avond)\b")
# De rubriek in de link zegt het ook: een kerkdienst ('/dienst/arend-kroes/', '?categorie=Kerkdienst') of
# de activiteiten voor de ouderen van het dorp ('/activiteiten-en-verenigingen/welzijn-ouderen').
SERVICE_PATH = re.compile(r"/(?:dienst|diensten|kerkdiensten?|vieringen|preekrooster)(?:/|$)|kerkdienst", re.IGNORECASE)
SENIORS_PATH = re.compile(r"/[\w-]*(?:ouderen|senioren|55-?plus|50-?plus)[\w-]*(?:/|$)", re.IGNORECASE)
# De pagina van een zaal met de naam van die zaal als titel: dat is de zaal, geen uitje.
# (Een uitje mét eigen naam dat naar de zaal linkt, blijft gewoon staan.)
VENUE_PAGE = re.compile(r"/(?:locations?|locaties?|venues?)/([^/]+)/?$")
# De rubriek in de link van een uitje ("/cursusprogramma/..."): zo deelt de organisator zelf in.
URL_KINDS: list[tuple[str, re.Pattern[str]]] = [
    ("lezing", re.compile(r"cursus|workshop|lezing|talks")),
    ("film", re.compile(r"^films?$|filmhuis|bioscoop|^bios$|^cinema$")),
    ("theater", re.compile(r"theater|voorstelling")),
    ("muziek", re.compile(r"concert|muziek")),
    ("kunst", re.compile(r"tentoonstelling|exposities?$")),
    ("natuur", re.compile(r"wandelingen|excursies")),
    ("sport", re.compile(r"^sport$")),
]

# Websites die vrijwel alleen een soort aanbieden. Alleen gebruikt als trefwoorden niets opleveren.
VENUE_RULES: dict[str, str] = {
    "simplon.nl": "muziek",
    "vera-groningen.nl": "muziek",
    "engelstede.nl": "muziek",                      # muziekpodium De Engelstede (bands zonder trefwoord)
    "jongeharten.podiumnederland.nl": "theater",    # festival Jonge Harten: theater voor jongeren
    # Festivals volgens vaste regel 3 (reden in overrides.json, 'namen'): het hele programma hoort erbij.
    "explorethenorth.nl": "festival",
    "visserijdagenharlingen.nl": "festival",
    # Wedstrijden: skûtsjesilen, motorraces en schaatsen.
    "ifks.frl": "sport",
    "skutsjesilen.nl": "sport",
    "ttcircuit.com": "sport",
    "ttassen.com": "sport",
    "thialf.nl": "sport",
    "schaatsen.nl": "sport",
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


# Een podium dat zelf zegt dat het een voorstelling, concert of film is, wint van deze losse trefwoorden.
PERFORMANCE_KINDS = {"muziek", "theater", "film"}
WEAK_KEYWORD_KINDS = {"eten", "natuur", "sport", "lezing"}

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

    # 2b. Een podium zegt zelf dat het een voorstelling, concert of film is: dat gaat voor een los trefwoord
    # over eten, natuur, sport of lezing in de titel ('Claudia de Breij', 'Oersoep', 'Amber Run').
    schema_kind = SCHEMA_KIND_HINTS.get(str(event.get("schemaType") or ""))
    section = url_section(event.get("url"))
    # Een film in de rubriek '/bios/' blijft een film, ook als de zaal elk uitje een TheaterEvent noemt
    # (De Nieuwe Kolk, 20 oktober 2026).
    if section and section[0] == "film" and event.get("schemaType") == "TheaterEvent":
        schema_kind = None
    first = next((k for k in PRIORITY if k in found), None)
    if schema_kind in PERFORMANCE_KINDS and first in WEAK_KEYWORD_KINDS:
        return result(schema_kind, "organisator",
                      f"de organisator noemt het een {event['schemaType']} (gaat voor trefwoord '{found[first][0]}')", 0.75)

    # 2c. Wandelingen en excursies zijn natuur, behalve bij een echte wedstrijd
    if "natuur" in found and race:
        return result("sport", "trefwoord", f"wedstrijd ({found['sport'][0]}) in de natuur", 0.85)
    for kind in PRIORITY:
        if kind in found:
            return result(kind, "trefwoord", f"trefwoord '{found[kind][0]}'", 0.8)

    # 3. Wat de organisator zelf op de pagina van het uitje zet
    if schema_kind:
        return result(schema_kind, "organisator", f"de organisator noemt het een {event['schemaType']}", 0.75)
    # Een film in de rubriek '/film/' van de bioscoop blijft een film, ook als de pagina 'komedie' of 'band' zegt.
    if section and section[0] == "film":
        return result("film", "organisator", f"de organisator zet het in de rubriek '{section[1]}'", 0.7)
    if page.get("soort") in KINDS and page.get("soort") != "festival":
        return result(page["soort"], "organisator", f"trefwoord '{page.get('woord')}' op de pagina van de organisator", 0.65)
    if section:
        return result(section[0], "organisator", f"de organisator zet het in de rubriek '{section[1]}'", 0.6)

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


def url_section(url: str | None) -> tuple[str, str] | None:
    """De soort uit de rubriek in een link: '/cursusprogramma/2118-...' of '/concerten/...'.
    Alleen de mappen, niet de naam van het uitje zelf (het laatste stuk), tenzij de link alleen
    uit een rubriek bestaat ('/cursusprogramma')."""
    parts = [p for p in urlparse(url or "").path.lower().split("/") if p]
    folders = parts[:-1] if len(parts) > 1 else parts
    for folder in folders:
        for kind, pattern in URL_KINDS:
            if pattern.search(folder):
                return kind, folder
    return None


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


# Gevonden bij het nalopen van de hele agenda (20 oktober 2026, 3.024 uitjes): menukopjes en knoppen,
# aanbiedingen, mededelingen, werkgroepen en vrijwilligerswerk, vaste dorps- en clubavonden, computerhulp.
SWEEP_HEADING = re.compile(r"^\W*(?://\s*\w+|\d+ excursies|alle datums|event info|ontdek alle \w+|nu te zien|leste nijs"
                           r"|maandelijkse weergave|tickets en info|uitgevoerde activiteiten|programma ?overzicht(?: \d{4})?"
                           r"|\w+ jaaragenda(?: \d{4})?|museum open|save the date|wordt verwacht\W*"
                           r"|in [\w ]+ is altijd wat te doen|bestel de serie|doors open .*|\w+ datum|thema: .{1,12}"
                           r"|(?:gereformeerde|hervormde|protestantse) kerk \w+|(?:\w+ ){1,2}algemeen)\W*$")
# Kopjes die ook de naam van een uitje kunnen zijn ('Welkom bij de Kerstmarkt', 'Thema: Halloween griezeltocht').
SWEEP_HEADING_SOFT = re.compile(r"^\W*(?:welkom bij .*|//.*)$")
SWEEP_NOT_OUTING = re.compile(
    r"\bpapierbak\b|straatverlichting|eerste schop in de grond|sinterklaas ?journaal|\bdaghap\b"
    r"|^(?:elke|lekker|lekkere)\b.*\bvoor \d+[,.]\d{2}!?$"
    r"|\bwerkgroep\b|\bklusdag\b|\b(?:voorjaars|najaars)werk\b|\b(?:najaars|voorjaars)bijeenkomst\b|\bvve\b|professionalsmeeting"
    r"|\bkovvie\b|kleding-? ?ruil-? ?rek|\bspekclub\b|\bmancave\b|powervrouwen|^praathuis$|^gezellige (?:middag|avond)$|^dorpsstee voor"
    r"|\bbiodanza\b|kaboutervoetbal|poeziekring|^volksdansen$|dinsdagavondvaren"
    r"|\bvieren dienst\b|\bdienst m\.? ?m\.? ?v\b|\b(?:50|55|60|65) ?\+")
# Hulp bij de computer of thuis (ook als 'workshop'); een lezing over hetzelfde onderwerp blijft staan.
SWEEP_HELP = re.compile(r"\blinux\b|\bchatgpt\b|\bdelpher\b|cyberveilig\w*|foto'?s digitaliseren|installatie ?avond"
                        r"|kinderen in een scheiding|computercursus|\bdigi ?(?:vitaler|sterker|taal)\b|zorgverzekeraar"
                        r"|digitale nalatenschap|raadplegen van digitale|\bseniorweb\b")
# Het feest van de eigen club na de laatste thuiswedstrijd ('Létste thúswedstrydfeest VV Suameer').
SWEEP_CLUB_PARTY = re.compile(r"thu(?:is|s)wedstr\w*feest")
SWEEP_PUBLIC = re.compile(r"lezing|debat|excursie|wandel\w*|workshop|feest|party|\bdans|\blive\b|voorstelling")


def not_an_outing(event: dict) -> str | None:
    """De reden waarom dit geen uitje is (een gewone kerkdienst), of None."""
    title = normalize(event.get("title") or "")
    if ADULT_ONLY.search(title):
        return f"alleen voor volwassenen: '{event.get('title')}'"
    public = SERVICE_PUBLIC.search(title) or PUBLIC_EVENT.search(title)
    if SWEEP_HEADING.match(title) or (SWEEP_HEADING_SOFT.match(title) and not public and not SWEEP_PUBLIC.search(title)):
        return f"geen naam van een uitje: '{event.get('title')}'"
    if SWEEP_NOT_OUTING.search(title) and not SERVICE_PUBLIC.search(title) and not SWEEP_PUBLIC.search(title):
        return f"niet noemenswaardig (vrijwilligers, werkgroep, vaste avond): '{event.get('title')}'"
    if SWEEP_CLUB_PARTY.search(title):
        return f"alleen voor leden of dorpsbewoners: '{event.get('title')}'"
    if SWEEP_HELP.search(title) and not re.search(r"lezing|debat", title):
        return f"hulp bij de computer of thuis: '{event.get('title')}'"
    if MEMBERS_ONLY.search(title) or (MEMBERS_UNLESS_PUBLIC.search(title) and not PUBLIC_EVENT.search(title)
                                         and not re.search(r"^open |voor iedereen", title)):
        return f"alleen voor leden of dorpsbewoners: '{event.get('title')}'"
    if TEAM_MATCH.match(title):
        return f"competitiewedstrijd van een club: '{event.get('title')}'"
    session = CLUB_SESSION.match(re.sub(r"^\W+", "", title))   # ook met een plaatje ervoor ('🃏 Klaverjassen')
    if session and not PUBLIC_EVENT.search(title):
        return f"vaste les of clubactiviteit: '{event.get('title')}'"
    if CLUB_INTERNAL.search(title) or (CLUB_GAME.search(title) and not CLUB_GAME_PUBLIC.search(title)):
        return f"vaste les of clubactiviteit: '{event.get('title')}'"
    if SENIORS_ONLY.search(title) and not SENIORS_PUBLIC.search(title):
        return f"voor de ouderen van het dorp: '{event.get('title')}'"
    if VILLAGE_ROUTINE.search(title) and not ROUTINE_PUBLIC.search(title):
        return f"niet noemenswaardig (vaste ontmoeting in het dorp): '{event.get('title')}'"
    hall = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    if (VILLAGE_HALL.search(normalize(hall.get("name") or "")) and VILLAGE_HALL_ACTIVITY.search(title)
            and not ROUTINE_PUBLIC.search(title) and not VILLAGE_HALL_PUBLIC.search(title)):
        return f"niet noemenswaardig (samen eten of bingo in het dorpshuis): '{event.get('title')}'"
    if SERVICE_OR_MEETING.search(title) and not SERVICE_PUBLIC.search(title):
        return f"niet noemenswaardig (hulp, cursus of bijeenkomst): '{event.get('title')}'"
    if NOT_A_TITLE.match(title.strip(" .:!")) or PAGE_HEADING.match(title):
        return f"geen naam van een uitje: '{event.get('title')}'"
    if CLUB_ONLY.match(title.strip(" .:!")) and not _matches(title):
        return f"club of vaste ontmoeting: '{event.get('title')}'"
    if SHOPS_ONLY.search(title) and not _matches(title):
        return f"alleen de winkels open: '{event.get('title')}'"
    link = urlparse(event.get("url") or "")
    if SERVICE_PATH.search(f"{link.path}?{link.query}") and not PUBLIC_EVENT.search(title):
        return f"kerkdienst (rubriek in de link): '{event.get('title')}'"
    if SENIORS_PATH.search(link.path) and not SENIORS_PUBLIC.search(title):
        return f"voor de ouderen van het dorp (rubriek in de link): '{event.get('title')}'"
    venue_page = VENUE_PAGE.search(link.path)
    if venue_page and normalize(venue_page.group(1).replace("-", " ")) == title:
        return f"de pagina van een zaal, geen uitje: '{event.get('title')}'"
    venue = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    # (Is de 'zaal' alleen de plaats, zoals bij een tournee, dan blijft het uitje staan.)
    if venue.get("name") and normalize(venue["name"]) == title and title != normalize(venue.get("city") or ""):
        return f"de naam van de zaal, geen uitje: '{event.get('title')}'"
    hit = NOT_AN_OUTING.search(title)
    return f"geen uitje: '{hit.group(0)}'" if hit else None
