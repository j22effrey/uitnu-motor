"""De vaste indeling van UITNU v2: elf soorten plus 'overig', en de labels."""

KINDS: dict[str, str] = {
    "muziek": "Muziek",
    "festival": "Festival",
    "theater": "Theater en comedy",
    "film": "Film",
    "markt": "Markt en beurs",
    "feest": "Feest en kermis",
    "sport": "Sport",
    "natuur": "Natuur en buiten",
    "kunst": "Kunst en erfgoed",
    "lezing": "Lezing en workshop",
    "eten": "Eten en drinken",
    "overig": "Overig",
}

TAGS: dict[str, str] = {
    "gratis": "Gratis",
    "kinderen": "Voor kinderen",
    "buiten": "Buiten",
    "meerdaags": "Meerdaags",
    "festival": "Festival",
}

# Oude categorie uit de eerste pipeline -> soort. Alleen gebruikt als niets anders past.
LEGACY_HINTS: dict[str, str] = {
    "food": "eten",
    "markt": "markt",
    "expo": "kunst",
    "feest": "feest",
    "kermis": "feest",
    "festival": "festival",
    "sport": "sport",
    "muziek": "muziek",
}

# Bij 'podium en cultuur' wist de eerste pipeline vaak de discipline al (soms van de organisator zelf).
DISCIPLINE_HINTS: dict[str, str] = {
    "muziek": "muziek",
    "klassiek_opera": "muziek",
    "theater": "theater",
    "cabaret": "theater",
    "dans": "theater",
    "film": "film",
    "kunst_expo": "kunst",
    "literatuur": "lezing",
}

# Soort plek in OpenStreetMap -> soort uitje dat daar meestal is. Alleen als de titel niets zegt.
OSM_KIND_HINTS: dict[str, str] = {
    "theatre": "theater",
    "music_venue": "muziek",
    "nightclub": "muziek",
    "cinema": "film",
    "arts_centre": "kunst",
    "museum": "kunst",
    "gallery": "kunst",
    "library": "lezing",
    "nature_reserve": "natuur",
    "zoo": "natuur",
    "sports_centre": "sport",
    "stadium": "sport",
}
