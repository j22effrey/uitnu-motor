"""Rules that keep discovery signals separate from publishable event records.

The project deliberately prefers missing an uncertain event over presenting a permit
application as a confirmed fact. These rules are conservative and explainable.
"""
from __future__ import annotations
from dataclasses import dataclass
from .event_model import RawEvent

@dataclass(frozen=True)
class Decision:
    action: str  # publish | review | suppress
    confidence: int  # 0..100
    reason: str


def decide(e: RawEvent) -> Decision:
    if e.verification_status == 'withdrawn_or_denied':
        return Decision('suppress',100,'Officiële bron vermeldt ingetrokken/geweigerd; niet als actief evenement tonen.')
    has_date=bool(e.start_at)
    has_place=bool((e.lat is not None and e.lon is not None) or e.city or e.venue or e.address)
    has_source=bool(e.source_url)
    complete=has_date and has_place and has_source

    if e.verification_status == 'permit_granted' and complete:
        return Decision('publish',92,'Vergunning verleend en kernvelden aanwezig; toon status expliciet.')
    if e.verification_status == 'organizer_confirmed' and complete:
        return Decision('publish',90,'Organisator/ticketfeed bevestigt event en kernvelden zijn aanwezig.')
    if e.verification_status == 'open_data_confirmed' and e.source_type == 'open_data' and complete:
        return Decision('publish',86,'Gestructureerde open-databron met datum, plaats en bronlink.')
    if e.source_type in {'structured_web','calendar_feed','ticketing'} and complete:
        return Decision('publish',82,'Gestructureerde bron met datum, plaats en bronlink.')
    if e.verification_status in {'permit_applied','notification','municipal_calendar'} and complete:
        return Decision('review',55,'Gemeentelijke planning is alleen een ontdekkingssignaal; niet publiek tonen zonder onafhankelijke bevestiging of verleende vergunning.')
    if e.verification_status == 'community_tip':
        return Decision('review',35,'Bezoekerstip moet op bron/dubbeling worden gecontroleerd.')
    if not complete:
        return Decision('review',25,'Een of meer kernvelden ontbreken; eerst verrijken/geocoden/controleren.')
    return Decision('review',45,'Bron gevonden maar status/kwaliteit is onvoldoende voor automatische publicatie.')