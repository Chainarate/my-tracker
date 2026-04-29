"""
Centralized configuration for the Chelsea Transfer Tracker.

Zero-cost architecture (v3):
- Ingestion via public RSS feeds only (no Reddit OAuth, no PRAW).
- AI analysis via Groq free tier (Llama 3.3 70B).

The only secret required at runtime is GROQ_API_KEY.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


def _required(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {key}. "
            "Verify the Harness Secrets Manager binding for this stage."
        )
    return val


def _optional(key: str, default: str) -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class GroqConfig:
    api_key: str
    model: str = "llama-3.1-8b-instant"      # free tier, 500K tokens/day (5x of 70B)
    temperature: float = 0.0
    max_output_tokens: int = 768
    request_timeout: float = 30.0


@dataclass(frozen=True)
class RedditRSSConfig:
    """Reddit-via-RSS — no API authentication required."""
    feed_url: str = "https://old.reddit.com/r/chelseafc/new/.rss"
    max_entries: int = 75


@dataclass(frozen=True)
class NewsRSSConfig:
    """Curated Chelsea-related news feeds (RSS, public, no auth)."""
    feeds: List[str] = field(
        default_factory=lambda: [
            "https://www.chelseafc.com/en/rss-feeds/news",
            "https://www.football.london/chelsea-fc/?service=rss",
            "https://www.skysports.com/rss/12040",                       # Sky Sports - Chelsea
            "https://feeds.bbci.co.uk/sport/football/teams/chelsea/rss.xml",
        ]
    )
    max_entries_per_feed: int = 25


@dataclass(frozen=True)
class StorageConfig:
    backend: str = "local"        # local | s3 | gcs
    bucket: str = ""
    prefix: str = "chelsea-tracker/"
    output_filename: str = "chelsea_tracker.csv"
    aws_region: str = "ap-southeast-1"


@dataclass(frozen=True)
class AppConfig:
    groq: GroqConfig
    reddit_rss: RedditRSSConfig
    news_rss: NewsRSSConfig
    storage: StorageConfig
    log_level: str = "INFO"
    user_agent: str = (
        "chelsea-transfer-tracker/3.0 (+https://github.com/hocco/chelsea-transfer-tracker)"
    )


def load_config() -> AppConfig:
    return AppConfig(
        groq=GroqConfig(
            api_key=_required("GROQ_API_KEY"),
            model=_optional("GROQ_MODEL", "llama-3.3-70b-versatile"),
        ),
        reddit_rss=RedditRSSConfig(
            feed_url=_optional(
                "REDDIT_RSS_URL",
                "https://old.reddit.com/r/chelseafc/new/.rss",
            ),
            max_entries=int(_optional("REDDIT_RSS_MAX_ENTRIES", "75")),
        ),
        news_rss=NewsRSSConfig(),
        storage=StorageConfig(
            backend=_optional("STORAGE_BACKEND", "local"),
            bucket=_optional("STORAGE_BUCKET", ""),
            prefix=_optional("STORAGE_PREFIX", "chelsea-tracker/"),
            aws_region=_optional("AWS_REGION", "ap-southeast-1"),
        ),
        log_level=_optional("LOG_LEVEL", "INFO"),
    )
