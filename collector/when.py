"""Datum en tijd uit de vormen die agenda's echt gebruiken, als ISO-tekst ('2026-10-17T20:30').

Voor lezers die per bron ingesteld worden (json_api, html_cards). Bekende vormen:
- ISO 8601: '2026-10-16T20:00:00+02:00' of '2026-10-17 00:00:00.000000'
- een getal (seconden sinds 1970, zoals WordPress-velden): 1792713600
- Nederlands met jaar: 'za 17 okt 2026', '17 oktober 2026', '16-10-2026 / 10:00', '22/10/2026 20:15'
- Nederlands zonder jaar met weekdag: 'za 17 okt', 'do 15.10' (de weekdag bepaalt het jaar)
- Engels zonder jaar met weekdag: 'Thursday 15 October', 'Sat 28 Nov 2026'
De tijd mag apart staan ('20:30', '20.30 uur', 'doors: 20:00 | start: 20:30', '09:00 & 10:30'):
de eerste tijd telt, of de tijd na 'start'.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MONTHS = {
    "januari": 1, "jan": 1, "january": 1,
    "februari": 2, "feb": 2, "february": 2,
    "maart": 3, "mrt": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "jun": 6, "june": 6,
    "juli": 7, "jul": 7, "july": 7,
    "augustus": 8, "aug": 8, "august": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10, "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
WEEKDAYS = {
    "ma": 0, "maandag": 0, "mon": 0, "monday": 0,
    "di": 1, "dinsdag": 1, "tue": 1, "tues": 1, "tuesday": 1,
    "wo": 2, "woensdag": 2, "wed": 2, "wednesday": 2,
    "do": 3, "donderdag": 3, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "vr": 4, "vrijdag": 4, "fri": 4, "friday": 4,
    "za": 5, "zaterdag": 5, "sat": 5, "saturday": 5,
    "zo": 6, "zondag": 6, "sun": 6, "sunday": 6,
}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_WEEKDAY = "|".join(sorted(WEEKDAYS, key=len, reverse=True))

# Met tijdzone ('2026-10-16T23:30:00Z' of '+02:00'): omrekenen naar Nederlandse tijd.
ZONED_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})")
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")
NUMERIC_RE = re.compile(r"(?<![\d])(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})(?!\d)")
WORD_RE = re.compile(rf"(?:\b({_WEEKDAY})\.?,?\s+)?(\d{{1,2}})\s+({_MONTH})\.?(?:\s+(20\d{{2}}))?\b", re.I)
SHORT_RE = re.compile(rf"\b({_WEEKDAY})\.?\s+(\d{{1,2}})\.(\d{{1,2}})(?![\d.])", re.I)
START_RE = re.compile(r"\b(?:start\w*|aanvang|begin\w*)\s*:?\s*(?:om\s*)?(\d{1,2})[:.](\d{2})", re.I)
TIME_RE = re.compile(r"(?<![\d.:])(\d{1,2})[:.](\d{2})(?![\d])")


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _by_weekday(month: int, day: int, weekday: int | None, today: date) -> date | None:
    """Een datum zonder jaar: het jaar waarin de weekdag klopt (dit of volgend jaar), anders de eerstvolgende."""
    options = [d for d in (_date(today.year - 1, month, day), _date(today.year, month, day), _date(today.year + 1, month, day)) if d]
    if weekday is not None:
        match = [d for d in options if d.weekday() == weekday and d >= date(today.year, 1, 1)]
        return match[0] if match else None
    # Zonder weekdag: de dichtstbijzijnde datum, waarbij tot twee maanden terug nog 'dit jaar' is
    # (een tentoonstelling 't/m 12 okt' op 16 oktober is net voorbij, niet volgend jaar).
    recent = [d for d in options if (today - d).days <= 60]
    return min(recent, key=lambda d: abs((d - today).days)) if recent else None


def parse_time(text) -> str | None:
    """'20:30' uit '20.30 uur', 'doors: 20:00 | start: 20:30' of '09:00 & 10:30'."""
    text = str(text or "")
    for regex in (START_RE, TIME_RE):
        m = regex.search(text)
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def parse_day(value, today: date) -> tuple[date | None, str | None]:
    """De dag (en een tijd als die in dezelfde tekst staat)."""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit() and len(value.strip()) >= 9):
        moment = datetime.fromtimestamp(int(value), tz=timezone.utc)
        return moment.date(), None
    text = " ".join(str(value or "").split())
    if not text:
        return None, None
    zoned = ZONED_RE.search(text)
    if zoned:
        try:
            moment = datetime.fromisoformat(zoned.group(0).replace("Z", "+00:00")).astimezone(AMSTERDAM)
            clock = moment.strftime("%H:%M")
            return moment.date(), None if clock == "00:00" else clock
        except ValueError:
            pass
    m = ISO_RE.search(text)
    if m:
        day = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        clock = f"{m.group(4)}:{m.group(5)}" if m.group(4) and (m.group(4), m.group(5)) != ("00", "00") else None
        return day, clock
    m = NUMERIC_RE.search(text)
    if m:
        rest = text[m.end():]
        return _date(int(m.group(3)), int(m.group(2)), int(m.group(1))), parse_time(rest)
    m = WORD_RE.search(text)
    if m:
        weekday = WEEKDAYS.get(m.group(1).lower()) if m.group(1) else None
        month = MONTHS[m.group(3).lower()]
        if m.group(4):
            return _date(int(m.group(4)), month, int(m.group(2))), parse_time(text[m.end():])
        return _by_weekday(month, int(m.group(2)), weekday, today), parse_time(text[m.end():])
    m = SHORT_RE.search(text)
    if m:
        return _by_weekday(int(m.group(3)), int(m.group(2)), WEEKDAYS[m.group(1).lower()], today), parse_time(text[m.end():])
    return None, None


def parse_when(day_value, time_value=None, *, today: date | None = None) -> str | None:
    """'2026-10-17T20:30', '2026-10-17' (tijd onbekend) of None als de datum niet te lezen is."""
    today = today or date.today()
    day, clock = parse_day(day_value, today)
    if not day:
        return None
    clock = parse_time(time_value) or clock
    return f"{day.isoformat()}T{clock}" if clock else day.isoformat()
