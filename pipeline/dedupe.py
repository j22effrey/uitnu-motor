"""Conservative duplicate matching for events from multiple sources."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
import hashlib, math, re, unicodedata
from .event_model import RawEvent, CanonicalEvent

STATUS_RANK={
    'withdrawn_or_denied':0,
    'unknown':1,
    'community_tip':1,
    'permit_applied':2,
    'notification':2,
    'municipal_calendar':2,
    'organizer_confirmed':3,
    'permit_granted':4,
}

def normalize_text(s: str|None)->str:
    if not s:return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(202[0-9]|editie|festival|evenement)\b',' ',s)
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())

def title_similarity(a:str,b:str)->float:
    a,b=normalize_text(a),normalize_text(b)
    if not a or not b:return 0.0
    if a==b:return 1.0
    ta,tb=set(a.split()),set(b.split())
    j=len(ta&tb)/max(1,len(ta|tb))
    seq=SequenceMatcher(None,a,b).ratio()
    return max(seq,(seq+j)/2)

def date_key(v:str)->str:
    return v[:10] if v else ''

def start_clock_time(v:str)->str:
    """Only compare times explicitly supplied by the source."""
    m=re.match(r'^\d{4}-\d{2}-\d{2}[T ]([01]\d|2[0-3]):([0-5]\d)',str(v or ''))
    return f'{m.group(1)}:{m.group(2)}' if m else ''

def km(a:RawEvent,b:RawEvent)->float|None:
    if None in (a.lat,a.lon,b.lat,b.lon):return None
    R=6371; p1=math.radians(a.lat);p2=math.radians(b.lat)
    dp=math.radians(b.lat-a.lat);dl=math.radians(b.lon-a.lon)
    h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(h))

def likely_duplicate(a:RawEvent,b:RawEvent)->bool:
    if date_key(a.start_at)!=date_key(b.start_at):return False
    ta,tb=start_clock_time(a.start_at),start_clock_time(b.start_at)
    if ta and tb and ta!=tb:return False
    sim=title_similarity(a.title,b.title)
    dist=km(a,b)
    same_city=normalize_text(a.city)==normalize_text(b.city) and bool(normalize_text(a.city))
    same_venue=normalize_text(a.venue)==normalize_text(b.venue) and bool(normalize_text(a.venue))
    if sim>=0.92 and (dist is None or dist<=3):return True
    if sim>=0.82 and (same_venue or (dist is not None and dist<=0.5)):return True
    if sim>=0.88 and same_city:return True
    return False

def _best(group:list[RawEvent],attr:str):
    vals=[getattr(x,attr) for x in group if getattr(x,attr) not in (None,'')]
    if not vals:return None
    return max(vals,key=lambda v:(len(str(v)),str(v)))

def merge_group(group:list[RawEvent])->CanonicalEvent:
    primary=max(group,key=lambda x:(STATUS_RANK.get(x.verification_status,1),bool(x.lat and x.lon),len(x.title)))
    status=max((x.verification_status for x in group),key=lambda s:STATUS_RANK.get(s,1))
    # A denied/withdrawn publication should not be overwritten by a weaker stale source.
    if any(x.verification_status=='withdrawn_or_denied' for x in group):status='withdrawn_or_denied'
    fingerprint='|'.join([normalize_text(primary.title),date_key(primary.start_at),normalize_text(primary.city or primary.venue)])
    cid='evt_'+hashlib.sha1(fingerprint.encode()).hexdigest()[:14]
    return CanonicalEvent(
        id=cid,title=primary.title,start_at=primary.start_at,end_at=_best(group,'end_at'),
        venue=_best(group,'venue'),address=_best(group,'address'),city=_best(group,'city'),
        lat=primary.lat if primary.lat is not None else _best(group,'lat'),
        lon=primary.lon if primary.lon is not None else _best(group,'lon'),
        category=_best(group,'category'),price_text=_best(group,'price_text'),
        verification_status=status,source_count=len(group),
        source_urls=sorted({x.source_url for x in group if x.source_url}),
        source_ids=sorted({x.source_id for x in group if x.source_id}),
    )

def dedupe(events:list[RawEvent])->list[CanonicalEvent]:
    groups=[]
    by_day=defaultdict(list)
    for e in events:
        day=date_key(e.start_at)
        for g in by_day[day]:
            if likely_duplicate(e,g[0]):
                g.append(e)
                break
        else:
            group=[e]
            groups.append(group)
            by_day[day].append(group)

    result=[merge_group(g) for g in groups]
    # Several distinct showtimes can have the same title/date/city fingerprint.
    # Disambiguate ALL of them, not only whichever appears second in the feed.
    # This keeps event IDs stable when the crawler changes its retrieval order.
    by_id=defaultdict(list)
    for item in result:
        by_id[item.id].append(item)
    for original, colliding in by_id.items():
        if len(colliding)<2:
            continue
        used=set()
        for item in colliding:
            identity='|'.join([
                str(item.start_at),
                normalize_text(item.venue),
                str(item.lat) if item.lat is not None else '',
                str(item.lon) if item.lon is not None else '',
            ])
            proposed=f"{original}_{hashlib.sha1(identity.encode()).hexdigest()[:12]}"
            if proposed in used:
                # Distinct records with identical date/time and venue must be
                # identifiable independently; source links are the last resort.
                identity+='|'+'|'.join(item.source_urls)
                proposed=f"{original}_{hashlib.sha1(identity.encode()).hexdigest()[:12]}"
            if proposed in used:
                raise ValueError("ambiguous canonical event identity")
            used.add(proposed)
            item.id=proposed
    return result
