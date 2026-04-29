"""
Cross-team RSS scraper for general football feeds (BBC Sport football,
The Guardian football, Sky Sports PL). Each item is matched against ALL
team keywords; an item attaches to the FIRST team that matches.

This is intentionally a 'best-effort wide net' — if Chelsea is mentioned
in a Guardian transfer story but Arsenal isn't, only Chelsea gets tagged.
If both are mentioned, the team listed first in TeamConfig wins (e.g. an
article about Chelsea-Arsenal swap deal will be filed under Chelsea).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import unescape
from time import mktime
from typing import List

import feedparser

from ..config import SharedFeedsConfig, TeamConfig
from ..models import TransferItem
from .reddit_rss_scraper import TRANSFER_KEYWORDS

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


class SharedNewsRSSScraper:
    """Scrape cross-team feeds; route each item to the first matching team."""

    def __init__(
        self,
        cfg: SharedFeedsConfig,
        teams: List[TeamConfig],
        user_agent: str,
    ) -> None:
        self.cfg = cfg
        self.teams = teams
        self.user_agent = user_agent

    def _match_team(self, blob_lower: str) -> TeamConfig | None:
        for team in self.teams:
            if any(kw in blob_lower for kw in team.all_keywords()):
                return team
        return None

    def _looks_like_transfer(self, blob_lower: str) -> bool:
        return any(kw in blob_lower for kw in TRANSFER_KEYWORDS)

    def fetch(self) -> List[TransferItem]:
        items: List[TransferItem] = []
        for feed_url in self.cfg.feeds:
            try:
                log.info("[SHARED] Parsing feed: %s", feed_url)
                parsed = feedparser.parse(
                    feed_url,
                    request_headers={"User-Agent": self.user_agent},
                )
                source_name = parsed.feed.get("title", feed_url)

                for entry in parsed.entries[: self.cfg.max_entries_per_feed]:
                    title = entry.get("title", "")
                    summary = _strip_html(
                        entry.get("summary", "") or entry.get("description", "")
                    )
                    blob = f"{title} {summary}".lower()
                    if not self._looks_like_transfer(blob):
                        continue
                    team = self._match_team(blob)
                    if not team:
                        continue

                    items.append(
                        TransferItem(
                            team=team.name,
                            source="shared_news_rss",
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
                log.warning("[SHARED] Feed %s failed: %s", feed_url, exc)

        log.info("[SHARED] produced %d items across %d team(s)",
                 len(items), len({i.team for i in items}))
        return items
