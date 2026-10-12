"""Generic Schema.org Event collector.

Many event/venue sites expose Event JSON-LD for search engines. Reusing those structured
fields is much more stable than scraping visual HTML. This collector only extracts factual
metadata and source URLs; it does not copy long editorial descriptions or images.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import json
from typing import Any, Iterable

USER_AGENT = "UITNU-MVP/0.3 (+event-discovery-prototype)"

@dataclass
class StructuredEvent:
    title: str | None
    start: str | None
    end: str | None
    venue: str | None
    street: str | None
    city: str | None
    postal_code: str | None
    latitude: float | None
    longitude: float | None
    price: str | None
    event_url: str | None
    source_url: str
    event_type: str | None = None  # schema.org-soort, bijvoorbeeld 'MusicEvent' of 'TheaterEvent'

class _LDParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_ld=False
        self.buf=[]
        self.blocks=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower()!='script': return
        d={k.lower():v for k,v in attrs}
        if (d.get('type') or '').lower()=='application/ld+json':
            self.in_ld=True; self.buf=[]
    def handle_endtag(self, tag):
        if tag.lower()=='script' and self.in_ld:
            self.blocks.append(''.join(self.buf)); self.in_ld=False; self.buf=[]
    def handle_data(self, data):
        if self.in_ld: self.buf.append(data)


def _walk(value: Any) -> Iterable[dict]:
    if isinstance(value, list):
        for x in value: yield from _walk(x)
    elif isinstance(value, dict):
        yield value
        for k in ('@graph','itemListElement','item'):
            if k in value: yield from _walk(value[k])


def _event_type(o: dict) -> str | None:
    """De meest specifieke schema.org-soort: 'MusicEvent' in plaats van 'Event'."""
    types = o.get('@type')
    types = types if isinstance(types, list) else [types]
    specific = [str(t) for t in types if isinstance(t, str) and t != 'Event'
                and (t.lower().endswith('event') or t == 'Festival')]
    return specific[0] if specific else None


def _is_event(o: dict) -> bool:
    t=o.get('@type')
    if isinstance(t,list): return any(str(x).lower().endswith('event') for x in t)
    return isinstance(t,str) and t.lower().endswith('event')


def _address(loc: Any) -> tuple[str|None,str|None,str|None]:
    if not isinstance(loc,dict): return None,None,None
    a=loc.get('address')
    if isinstance(a,str): return a,None,None
    if not isinstance(a,dict): return None,None,None
    return a.get('streetAddress'),a.get('addressLocality'),a.get('postalCode')


def _coords(loc: Any) -> tuple[float|None,float|None]:
    if not isinstance(loc,dict): return None,None
    g=loc.get('geo')
    if not isinstance(g,dict): return None,None
    try: lat=float(g.get('latitude')) if g.get('latitude') is not None else None
    except (TypeError,ValueError): lat=None
    try: lon=float(g.get('longitude')) if g.get('longitude') is not None else None
    except (TypeError,ValueError): lon=None
    return lat,lon


def _price(o: dict) -> str|None:
    offers=o.get('offers')
    if isinstance(offers,list): offers=offers[0] if offers else None
    if not isinstance(offers,dict): return None
    p=offers.get('price'); cur=offers.get('priceCurrency')
    if p is None: return None
    return f"{cur or ''} {p}".strip()


def parse_html(html: str, source_url: str) -> list[StructuredEvent]:
    p=_LDParser(); p.feed(html)
    result=[]; seen=set()
    for raw in p.blocks:
        try: data=json.loads(raw)
        except Exception: continue
        for o in _walk(data):
            if not _is_event(o): continue
            loc=o.get('location')
            if isinstance(loc,list): loc=loc[0] if loc else None
            street,city,pc=_address(loc)
            lat,lon=_coords(loc)
            venue=loc.get('name') if isinstance(loc,dict) else (loc if isinstance(loc,str) else None)
            url=o.get('url') or source_url
            if isinstance(url,dict): url=url.get('@id')
            url=urljoin(source_url,url) if isinstance(url,str) else source_url
            key=(o.get('name'),o.get('startDate'),venue,city)
            if key in seen: continue
            seen.add(key)
            result.append(StructuredEvent(
                title=o.get('name'), start=o.get('startDate'), end=o.get('endDate'),
                venue=venue, street=street, city=city, postal_code=pc,
                latitude=lat, longitude=lon, price=_price(o), event_url=url, source_url=source_url,
                event_type=_event_type(o),
            ))
    return result


def fetch(url: str) -> list[StructuredEvent]:
    req=Request(url,headers={'User-Agent':USER_AGENT,'Accept':'text/html'})
    with urlopen(req,timeout=25) as r:
        html=r.read().decode(r.headers.get_content_charset() or 'utf-8','replace')
    return parse_html(html,url)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('url');a=ap.parse_args()
    print(json.dumps([asdict(x) for x in fetch(a.url)],ensure_ascii=False,indent=2))
