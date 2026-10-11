from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class RawEvent:
    source_name: str
    source_type: str
    source_url: str
    source_id: str | None
    title: str
    start_at: str
    end_at: str | None = None
    venue: str | None = None
    address: str | None = None
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    category: str | None = None
    price_text: str | None = None
    description: str | None = None
    verification_status: str = 'unknown'
    raw: dict[str,Any] = field(default_factory=dict)

@dataclass
class CanonicalEvent:
    id: str
    title: str
    start_at: str
    end_at: str | None
    venue: str | None
    address: str | None
    city: str | None
    lat: float | None
    lon: float | None
    category: str | None
    price_text: str | None
    verification_status: str
    source_count: int
    source_urls: list[str]
    source_ids: list[str]

    def asdict(self): return asdict(self)
