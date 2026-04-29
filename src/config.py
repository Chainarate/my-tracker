"""
Centralized configuration for the Premier League Transfer Tracker.

Zero-cost architecture (v4):
- Multi-team: Chelsea, Arsenal, Man Utd, Man City, Newcastle, Tottenham.
- Ingestion via public RSS feeds only (no OAuth).
- AI analysis via Groq free tier (Llama 3.1 8B by default).

The only secret required at runtime is GROQ_API_KEY.
DISCORD_WEBHOOK_URL is optional (alerts disabled if unset).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Tuple


def _required(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {key}. "
            "Verify the Harness/GitHub Actions secret binding."
        )
    return val


def _optional(key: str, default: str) -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class GroqConfig:
    api_key: str
    model: str = "llama-3.1-8b-instant"
    temperature: float = 0.0
    max_output_tokens: int = 768
    request_timeout: float = 30.0


@dataclass(frozen=True)
class TeamConfig:
    """One Premier-League club's scrape sources + name-detection keywords."""
    name: str                       # human-readable team name, e.g. "Arsenal"
    primary_keyword: str            # main lowercase string to match in title/body
    aliases: Tuple[str, ...] = ()   # additional accepted keywords (lowercase)
    reddit_rss_url: str = ""
    news_feeds: Tuple[str, ...] = ()
    max_reddit_entries: int = 50
    max_entries_per_feed: int = 15

    def all_keywords(self) -> Tuple[str, ...]:
        return (self.primary_keyword, *self.aliases)


def _default_teams() -> List[TeamConfig]:
    """
    Each team scrapes from 3+ independent news sources:
      - BBC Sport (national broadcaster, conservative reporting)
      - The Guardian (broadsheet, named bylines)
      - A regional Reach plc paper (football.london / MEN / Chronicle Live /
        Liverpool Echo) - heavy transfer-rumour coverage
      - Club-official feed where available (chelseafc.com, liverpool.com)
      - Subreddit RSS for fan-sourced + leaked Tier-1 reports
    """
    return [
        TeamConfig(
            name="Chelsea",
            primary_keyword="chelsea",
            aliases=("the blues", "cfc"),
            reddit_rss_url="https://old.reddit.com/r/chelseafc/new/.rss",
            news_feeds=(
                "https://www.chelseafc.com/en/rss-feeds/news",
                "https://www.football.london/chelsea-fc/?service=rss",
                "https://feeds.bbci.co.uk/sport/football/teams/chelsea/rss.xml",
                "https://www.theguardian.com/football/chelsea/rss",
            ),
        ),
        TeamConfig(
            name="Arsenal",
            primary_keyword="arsenal",
            aliases=("gunners", "afc"),
            reddit_rss_url="https://old.reddit.com/r/Gunners/new/.rss",
            news_feeds=(
                "https://www.football.london/arsenal-fc/?service=rss",
                "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml",
                "https://www.theguardian.com/football/arsenal/rss",
            ),
        ),
        TeamConfig(
            name="Manchester United",
            primary_keyword="manchester united",
            aliases=("man united", "man utd", "red devils", "mufc"),
            reddit_rss_url="https://old.reddit.com/r/reddevils/new/.rss",
            news_feeds=(
                "https://feeds.bbci.co.uk/sport/football/teams/manchester-united/rss.xml",
                "https://www.theguardian.com/football/manchester-united/rss",
                "https://www.manchestereveningnews.co.uk/all-about/manchester-united-fc/?service=rss",
            ),
        ),
        TeamConfig(
            name="Manchester City",
            primary_keyword="manchester city",
            aliases=("man city", "mcfc"),
            reddit_rss_url="https://old.reddit.com/r/MCFC/new/.rss",
            news_feeds=(
                "https://feeds.bbci.co.uk/sport/football/teams/manchester-city/rss.xml",
                "https://www.theguardian.com/football/manchestercity/rss",
                "https://www.manchestereveningnews.co.uk/all-about/manchester-city-fc/?service=rss",
            ),
        ),
        TeamConfig(
            name="Newcastle",
            primary_keyword="newcastle",
            aliases=("magpies", "nufc", "toon"),
            reddit_rss_url="https://old.reddit.com/r/NUFC/new/.rss",
            news_feeds=(
                "https://feeds.bbci.co.uk/sport/football/teams/newcastle-united/rss.xml",
                "https://www.theguardian.com/football/newcastleunited/rss",
                "https://www.chroniclelive.co.uk/all-about/newcastle-united-fc/?service=rss",
            ),
        ),
        TeamConfig(
            name="Tottenham",
            primary_keyword="tottenham",
            aliases=("spurs", "thfc", "coys"),
            reddit_rss_url="https://old.reddit.com/r/coys/new/.rss",
            news_feeds=(
                "https://www.football.london/tottenham-hotspur-fc/?service=rss",
                "https://feeds.bbci.co.uk/sport/football/teams/tottenham-hotspur/rss.xml",
                "https://www.theguardian.com/football/tottenham-hotspur/rss",
            ),
        ),
        TeamConfig(
            name="Liverpool",
            primary_keyword="liverpool",
            aliases=("the reds", "lfc", "anfield"),
            reddit_rss_url="https://old.reddit.com/r/LiverpoolFC/new/.rss",
            news_feeds=(
                "https://www.liverpool.com/?service=rss",
                "https://feeds.bbci.co.uk/sport/football/teams/liverpool/rss.xml",
                "https://www.theguardian.com/football/liverpool/rss",
                "https://www.liverpoolecho.co.uk/all-about/liverpool-fc/?service=rss",
            ),
        ),
    ]


@dataclass(frozen=True)
class SharedFeedsConfig:
    """Cross-team feeds. Each item is matched against ALL teams' keywords."""
    feeds: Tuple[str, ...] = (
        # BBC Sport - all football (transfer items often leak here first)
        "https://feeds.bbci.co.uk/sport/football/rss.xml",
        # The Guardian - top football stories across all clubs
        "https://www.theguardian.com/football/rss",
        # Sky Sports - generic Premier League feed
        "https://www.skysports.com/rss/11661",
    )
    max_entries_per_feed: int = 25


@dataclass(frozen=True)
class StorageConfig:
    backend: str = "local"        # local | s3 | gcs
    bucket: str = ""
    prefix: str = "transfer-tracker/"
    output_filename: str = "chelsea_tracker.csv"   # kept for path-compat with existing repo
    aws_region: str = "ap-southeast-1"


@dataclass(frozen=True)
class AppConfig:
    groq: GroqConfig
    teams: List[TeamConfig]
    shared_feeds: SharedFeedsConfig
    storage: StorageConfig
    log_level: str = "INFO"
    user_agent: str = (
        "transfer-tracker/5.0 (+https://github.com/hocco/chelsea-transfer-tracker)"
    )


def load_config() -> AppConfig:
    return AppConfig(
        groq=GroqConfig(
            api_key=_required("GROQ_API_KEY"),
            model=_optional("GROQ_MODEL", "llama-3.1-8b-instant"),
        ),
        teams=_default_teams(),
        shared_feeds=SharedFeedsConfig(),
        storage=StorageConfig(
            backend=_optional("STORAGE_BACKEND", "local"),
            bucket=_optional("STORAGE_BUCKET", ""),
            prefix=_optional("STORAGE_PREFIX", "transfer-tracker/"),
            output_filename=_optional("OUTPUT_FILENAME", "chelsea_tracker.csv"),
            aws_region=_optional("AWS_REGION", "ap-southeast-1"),
        ),
        log_level=_optional("LOG_LEVEL", "INFO"),
    )
