"""Shared data models used by scrapers, the analyzer, and the storage layer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class TransferItem:
    """One canonical transfer-news record before AI enrichment."""
    team: str             # 'Chelsea' | 'Arsenal' | 'Manchester United' | ...
    source: str           # 'reddit_rss' | 'news_rss'
    source_name: str      # 'r/chelseafc' | 'BBC Sport - Chelsea' ...
    title: str
    url: str
    body: str
    published_at: datetime
    author: Optional[str] = None
    external_id: Optional[str] = None  # rss guid / reddit thing id

    def fingerprint(self) -> str:
        """Stable id used to dedup across runs (team-scoped)."""
        return f"{self.team}:{self.source}:{self.external_id or self.url}"


@dataclass
class AnalyzedItem:
    """A TransferItem enriched by Groq with structured transfer metadata."""
    item: TransferItem
    journalist_name: str
    transfer_claim: str
    tier: str
    hit_miss: str
    confidence: float
    reasoning: str
    analyzed_at: datetime

    def to_row(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.item.fingerprint(),
            "team": self.item.team,
            "source": self.item.source,
            "source_name": self.item.source_name,
            "title": self.item.title,
            "url": self.item.url,
            "author": self.item.author or "",
            "published_at": self.item.published_at.isoformat(),
            "journalist_name": self.journalist_name,
            "transfer_claim": self.transfer_claim,
            "tier": self.tier,
            "hit_miss": self.hit_miss,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "analyzed_at": self.analyzed_at.isoformat(),
        }
