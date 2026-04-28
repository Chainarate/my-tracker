"""
Reads Chelsea-related transfer chatter from r/chelseafc via the public RSS feed
(no PRAW, no OAuth, no client id/secret).

Reddit serves a public RSS feed for any subreddit listing:
    https://old.reddit.com/r/chelseafc/new/.rss

Reddit aggressively blocks non-browser User-Agents (returns an HTML "blocked"
page that breaks feedparser with "not well-formed"). To work around this we
fetch the bytes ourselves via urllib using a Chrome-like UA, then hand the
raw bytes to feedparser - which handles malformed input much better than the
default URL-fetching path.
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from time import mktime
from typing import List
import re

import feedparser

from ..config import RedditRSSConfig
from ..models import TransferItem

# Chrome-on-Mac UA. Reddit serves XML RSS to browsers; serves HTML blockpage
# to anything that looks like a bot (curl, python-requests, wget, etc.).
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

log = logging.getLogger(__name__)


TRANSFER_KEYWORDS = (
    "transfer", "signing", "agreement", "deal", "bid", "fee",
    "loan", "linked", "target", "tier 1", "tier 2", "tier 3",
    "medical", "here we go", "agreed", "sale", "release clause",
    "romano", "ornstein", "fabrizio",
)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    """Reddit RSS bodies are HTML-encoded; produce plain text."""
    if not s:
        return ""
    return unescape(_TAG_RE.sub("", s)).strip()


def _entry_published(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        ts = getattr(entry, key, None)
        if ts:
            return datetime.fromtimestamp(mktime(ts), tz=timezone.utc)
    return datetime.now(tz=timezone.utc)


def _looks_like_transfer(blob: str) -> bool:
    blob = blob.lower()
    return any(kw in blob for kw in TRANSFER_KEYWORDS)


class RedditRSSScraper:
    """Pulls posts from r/chelseafc via Reddit's free public RSS feed."""

    def __init__(self, cfg: RedditRSSConfig, user_agent: str) -> None:
        self.cfg = cfg
        self.user_agent = user_agent

    def _fetch_bytes(self) -> bytes | None:
        """Fetch Reddit RSS bytes with a Chrome UA. Returns None on failure."""
        req = urllib.request.Request(
            self.cfg.feed_url,
            headers={
                "User-Agent": BROWSER_UA,
                "Accept": "application/atom+xml, application/xml, text/xml, */*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            log.warning("Reddit RSS HTTP fetch failed: %s", exc)
            return None

    def fetch(self) -> List[TransferItem]:
        log.info("Fetching Reddit RSS feed: %s", self.cfg.feed_url)
        raw = self._fetch_bytes()
        if not raw:
            return []
        parsed = feedparser.parse(raw)

        if parsed.bozo and not parsed.entries:
            # Likely Reddit served an HTML blockpage even with a Chrome UA.
            preview = raw[:200].decode("utf-8", errors="replace")
            log.warning(
                "Reddit RSS feed parse failed: %s (response preview: %r)",
                parsed.bozo_exception, preview,
            )
            return []

        source_name = parsed.feed.get("title", "r/chelseafc")
        items: List[TransferItem] = []

        for entry in parsed.entries[: self.cfg.max_entries]:
            try:
                title = entry.get("title", "")
                body = _strip_html(entry.get("summary", "") or entry.get("content", [{"value": ""}])[0].get("value", ""))
                if not _looks_like_transfer(f"{title} {body}"):
                    continue

                items.append(
                    TransferItem(
                        source="reddit_rss",
                        source_name=source_name,
                        title=title,
                        url=entry.get("link", ""),
                        body=body[:4000],
                        published_at=_entry_published(entry),
                        author=entry.get("author"),
                        external_id=entry.get("id") or entry.get("link"),
                    )
                )
            except Exception as exc:
                log.warning("Skipping Reddit RSS entry due to error: %s", exc)

        log.info("Reddit RSS scraper produced %d candidate items", len(items))
        return items
