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
    "festival": "festival",
    "sport": "sport",
    "muziek": "muziek",
}
