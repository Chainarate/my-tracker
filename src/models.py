"""Shared data models used by scrapers, the analyzer, and the storage layer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class TransferItem:
    """One canonical transfer-news record before AI enrichment."""
    source: str           # 'reddit_rss' | 'news_rss'
    source_name: str      # 'r/chelseafc' | 'BBC Sport - Chelsea' ...
    title: str
    url: str
    body: str
    published_at: datetime
    author: Optional[str] = None
    external_id: Optional[str] = None  # rss guid / reddit thing id

    def fingerprint(self) -> str:
        """Stable id used to dedup across runs."""
        return f"{self.source}:{self.external_id or self.url}"


@dataclass
class AnalyzedItem:
    """A TransferItem enriched by Groq with structured transfer metadata."""
    item: TransferItem
    journalist_name: str          # e.g. "Fabrizio Romano", "Unknown"
    transfer_claim: str           # short factual claim, <= 240 chars
    tier: str                     # 'Tier 1' | 'Tier 2' | 'Tier 3' | 'Rumour' | 'Unknown'
    hit_miss: str                 # 'Hit' | 'Miss' | 'Pending' | 'Unknown'
    confidence: float             # 0.0 - 1.0
    reasoning: str                # short rationale, <= 400 chars
    analyzed_at: datetime

    def to_row(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.item.fingerprint(),
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
