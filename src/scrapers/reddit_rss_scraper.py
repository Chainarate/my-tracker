"""
Reads transfer chatter for one team from its subreddit RSS feed
(no PRAW, no OAuth, no client id/secret).

Reddit serves a public RSS feed for any subreddit listing, e.g.:
    https://old.reddit.com/r/chelseafc/new/.rss

Reddit aggressively blocks non-browser User-Agents (returns an HTML "blocked"
page that breaks feedparser with "not well-formed"). We fetch the bytes
ourselves via urllib using a Chrome-like UA, then hand the raw bytes to
feedparser - which handles malformed input much better than the URL path.
"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from time import mktime
from typing import List

import feedparser

from ..config import TeamConfig
from ..models import TransferItem

# Chrome-on-Mac UA. Reddit serves XML RSS to browsers; serves HTML blockpage
# to anything that looks like a bot (curl, python-requests, wget, etc.).
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Generic transfer signals we look for. Team-name match comes from TeamConfig.
TRANSFER_KEYWORDS = (
    "transfer", "signing", "agreement", "deal", "bid", "fee",
    "loan", "linked", "target", "tier 1", "tier 2", "tier 3",
    "medical", "here we go", "agreed", "sale", "release clause",
    "romano", "ornstein", "fabrizio", "plettenberg", "di marzio",
    "summer window", "january window", "transfer window",
    "swap", "departure", "exit", "wages", "contract", "extension",
)

# Items matching ANY of these are NOT transfer news (false positives).
# Filter at scrape-time saves Groq tokens AND reduces alert noise.
ANTI_TRANSFER_KEYWORDS = (
    "injury", "injured", "hamstring", "fitness", "surgery", "rehab",
    "ratings", "player ratings", "starting xi", "starting lineup",
    "match thread", "match report", "post-match", "live blog",
    "highlights", "what we learned", "tactical", "fixtures",
    "fan view", "fan reaction", "predictions",
)


def _looks_like_transfer(blob_lower: str) -> bool:
    """Returns True if the text mentions transfer-language AND lacks anti-keywords."""
    if not any(kw in blob_lower for kw in TRANSFER_KEYWORDS):
        return False
    # Even if a transfer keyword matches, reject obvious non-transfer content.
    if any(kw in blob_lower for kw in ANTI_TRANSFER_KEYWORDS):
        return False
    return True

_TAG_RE = re.compile(r"<[^>]+>")

log = logging.getLogger(__name__)


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


class RedditRSSScraper:
    """Pulls posts from a single team's subreddit via Reddit's free public RSS feed."""

    def __init__(self, team: TeamConfig, user_agent: str) -> None:
        self.team = team
        self.user_agent = user_agent

    def _fetch_bytes(self) -> bytes | None:
        if not self.team.reddit_rss_url:
            return None
        req = urllib.request.Request(
            self.team.reddit_rss_url,
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
            log.warning("[%s] Reddit RSS HTTP fetch failed: %s", self.team.name, exc)
            return None

    def _is_transfer(self, blob_lower: str) -> bool:
        return _looks_like_transfer(blob_lower)

    def fetch(self) -> List[TransferItem]:
        if not self.team.reddit_rss_url:
            return []
        log.info("[%s] Fetching Reddit RSS: %s", self.team.name, self.team.reddit_rss_url)
        raw = self._fetch_bytes()
        if not raw:
            return []
        parsed = feedparser.parse(raw)
        if parsed.bozo and not parsed.entries:
            log.warning("[%s] Reddit RSS parse failed: %s", self.team.name, parsed.bozo_exception)
            return []

        source_name = parsed.feed.get("title", f"r/{self.team.primary_keyword}")
        items: List[TransferItem] = []
        for entry in parsed.entries[: self.team.max_reddit_entries]:
            try:
                title = entry.get("title", "")
                body = _strip_html(
                    entry.get("summary", "")
                    or entry.get("content", [{"value": ""}])[0].get("value", "")
                )
                blob = f"{title} {body}".lower()
                if not self._is_transfer(blob):
                    continue
                items.append(
                    TransferItem(
                        team=self.team.name,
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
                log.warning("[%s] Skipping Reddit entry due to error: %s", self.team.name, exc)

        log.info("[%s] Reddit RSS produced %d items", self.team.name, len(items))
        return items
