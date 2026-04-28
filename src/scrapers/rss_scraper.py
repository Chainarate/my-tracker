"""Pulls Chelsea transfer items from a curated set of public news RSS feeds."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from html import unescape
from time import mktime
from typing import List
import re

import feedparser

from ..config import NewsRSSConfig
from ..models import TransferItem

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
    def __init__(self, cfg: NewsRSSConfig, user_agent: str) -> None:
        self.cfg = cfg
        self.user_agent = user_agent

    def fetch(self) -> List[TransferItem]:
        items: List[TransferItem] = []
        for feed_url in self.cfg.feeds:
            try:
                log.info("Parsing news RSS feed: %s", feed_url)
                parsed = feedparser.parse(
                    feed_url,
                    request_headers={"User-Agent": self.user_agent},
                )
                source_name = parsed.feed.get("title", feed_url)

                for entry in parsed.entries[: self.cfg.max_entries_per_feed]:
                    title = entry.get("title", "")
                    summary = _strip_html(entry.get("summary", "") or entry.get("description", ""))
                    if "chelsea" not in (title + " " + summary).lower():
                        continue

                    items.append(
                        TransferItem(
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
                log.warning("News RSS feed %s failed: %s", feed_url, exc)

        log.info("News RSS scraper produced %d candidate items", len(items))
        return items
