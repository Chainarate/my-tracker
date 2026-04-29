"""Pulls per-team transfer items from a curated set of public news RSS feeds."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import unescape
from time import mktime
from typing import List

import feedparser

from ..config import TeamConfig
from ..models import TransferItem
from .reddit_rss_scraper import TRANSFER_KEYWORDS, _looks_like_transfer

log = logging.getLogger(__name__)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    if not s:
        return ""
    return unescape(_TAG_RE.sub("", s)).strip()


def _entry_published(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        ts = getattr(entry, key, None)
        if ts:
            return datetime.fromtimestamp(mktime(ts), tz=timezone.utc)
    return datetime.now(tz=timezone.utc)


class NewsRSSScraper:
    """Scrape one team's news feeds. Filters by team name AND transfer keywords."""

    def __init__(self, team: TeamConfig, user_agent: str) -> None:
        self.team = team
        self.user_agent = user_agent

    def _looks_like_transfer(self, blob_lower: str) -> bool:
        return _looks_like_transfer(blob_lower)

    def _mentions_team(self, blob_lower: str) -> bool:
        return any(kw in blob_lower for kw in self.team.all_keywords())

    def fetch(self) -> List[TransferItem]:
        items: List[TransferItem] = []
        for feed_url in self.team.news_feeds:
            try:
                log.info("[%s] Parsing news RSS: %s", self.team.name, feed_url)
                parsed = feedparser.parse(
                    feed_url,
                    request_headers={"User-Agent": self.user_agent},
                )
                source_name = parsed.feed.get("title", feed_url)

                for entry in parsed.entries[: self.team.max_entries_per_feed]:
                    title = entry.get("title", "")
                    summary = _strip_html(
                        entry.get("summary", "") or entry.get("description", "")
                    )
                    blob = f"{title} {summary}".lower()
                    if not self._mentions_team(blob):
                        continue
                    if not self._looks_like_transfer(blob):
                        continue

                    items.append(
                        TransferItem(
                            team=self.team.name,
                            source="news_rss",
                            source_name=source_name,
                            title=title,
                            url=entry.get("link", ""),
                            body=summary[:4000],
                            published_at=_entry_published(entry),
                            author=entry.get("author"),
                            external_id=entry.get("id") or entry.get("link"),
                        )
                    )
            except Exception as exc:
                log.warning("[%s] News RSS feed %s failed: %s", self.team.name, feed_url, exc)

        log.info("[%s] News RSS produced %d items", self.team.name, len(items))
        return items
