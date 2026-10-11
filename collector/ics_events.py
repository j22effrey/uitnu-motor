"""Tiny iCalendar event reader for public calendar feeds.

Supports the subset needed for event discovery: VEVENT, DTSTART/DTEND, SUMMARY,
LOCATION, URL, UID and DESCRIPTION. No external dependency required.
"""
from __future__ import annotations
from datetime import datetime
import re
from urllib.request import Request, urlopen
from pipeline.event_model import RawEvent


def unfold(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _iso_ical(v: str) -> str:
    v = v.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            dt = datetime.strptime(v, fmt)
            if fmt.endswith("Z"):
                return dt.isoformat() + "Z"
            return dt.isoformat()
        except ValueError:
            pass
    return v


def parse_ics(text: str, source_url: str, source_name: str = "iCalendar feed") -> list[RawEvent]:
    blocks: list[dict[str,str]] = []
    current = None
    for line in unfold(text):
        if line == "BEGIN:VEVENT": current = {}; continue
        if line == "END:VEVENT":
            if current is not None: blocks.append(current)
            current = None; continue
        if current is None or ":" not in line: continue
        left, value = line.split(":", 1)
        key = left.split(";", 1)[0].upper()
        current[key] = _unescape(value)
    out=[]
    for e in blocks:
        if not (e.get("SUMMARY") and e.get("DTSTART")): continue
        loc=e.get("LOCATION") or ""
        city=None
        if "," in loc: city=loc.split(",")[-1].strip()
        out.append(RawEvent(
            source_name=source_name, source_type="calendar_feed",
            source_url=e.get("URL") or source_url, source_id=e.get("UID"),
            title=e["SUMMARY"], start_at=_iso_ical(e["DTSTART"]),
            end_at=_iso_ical(e["DTEND"]) if e.get("DTEND") else None,
            venue=loc or None, city=city,
            description=(e.get("DESCRIPTION") or "")[:500] or None,
            verification_status="organizer_confirmed",
            raw={"source_feed": source_url},
        ))
    return out


def fetch(url: str, source_name: str = "iCalendar feed", timeout: float = 15) -> list[RawEvent]:
    req = Request(url, headers={"User-Agent":"UITNU-prototype/0.3"})
    with urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    return parse_ics(text, url, source_name)
