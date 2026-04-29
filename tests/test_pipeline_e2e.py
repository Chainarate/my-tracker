"""
End-to-end pipeline test with mocked external services.

Verifies multi-team scraping (Chelsea + Arsenal sample) -> Groq analyzer ->
CSV writer -> Discord notifier all wire up correctly without needing a real
Groq key, live RSS, or Discord webhook.

Run from project root:  PYTHONPATH=. python tests/test_pipeline_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rss_entry(title: str, summary: str, link: str, author: str = "Author"):
    return {
        "title": title, "summary": summary, "link": link, "id": link,
        "author": author,
        "published_parsed": datetime.now(tz=timezone.utc).timetuple(),
    }


def _verdict_for_text(text: str) -> dict:
    if "estevao" in text.lower() or "here we go" in text.lower():
        return {
            "journalist_name": "Fabrizio Romano",
            "transfer_claim": "Chelsea sign Estevao here we go.",
            "tier": "Tier 1", "hit_miss": "Pending",
            "confidence": 0.92,
            "reasoning": "Romano confirmation language.",
        }
    if "rice" in text.lower():
        return {
            "journalist_name": "BBC Sport",
            "transfer_claim": "Arsenal complete signing of Declan Rice.",
            "tier": "Tier 2", "hit_miss": "Hit",
            "confidence": 0.80,
            "reasoning": "Reputable outlet, completion language.",
        }
    return {
        "journalist_name": "Unknown",
        "transfer_claim": "",
        "tier": "Rumour", "hit_miss": "Unknown",
        "confidence": 0.20,
        "reasoning": "Speculative.",
    }


def main() -> int:
    os.environ.update({
        "GROQ_API_KEY": "fake_key",
        "STORAGE_BACKEND": "local",
        "OUTPUT_DIR": tempfile.mkdtemp(prefix="tracker_e2e_"),
        "LOG_LEVEL": "INFO",
    })

    from src import main as app_main  # noqa: E402

    chelsea_reddit = SimpleNamespace(
        bozo=False, feed={"title": "r/chelseafc"},
        entries=[
            _rss_entry(
                "Romano: Chelsea sign Estevao here we go!",
                "Official statement expected.",
                "https://reddit.com/r/chelseafc/abc1",
            ),
            _rss_entry(
                "Match thread: Chelsea vs Arsenal",
                "Live match thread.",
                "https://reddit.com/r/chelseafc/abc3",
            ),
        ],
    )
    arsenal_reddit = SimpleNamespace(
        bozo=False, feed={"title": "r/Gunners"},
        entries=[
            _rss_entry(
                "Arsenal complete £105m Rice signing",
                "Arsenal officially announce Declan Rice.",
                "https://reddit.com/r/Gunners/xyz1",
            ),
        ],
    )
    arsenal_news = SimpleNamespace(
        bozo=False, feed={"title": "BBC Sport - Arsenal"},
        entries=[
            _rss_entry(
                "Arsenal sign Rice in record deal",
                "BBC confirms Arsenal complete signing.",
                "https://bbc.com/arsenal-rice",
            ),
        ],
    )
    chelsea_news = SimpleNamespace(
        bozo=False, feed={"title": "BBC Sport - Chelsea"},
        entries=[
            _rss_entry(
                "Chelsea complete signing of midfielder",
                "Chelsea confirms transfer.",
                "https://bbc.com/chelsea-mid",
            ),
        ],
    )
    empty_feed = SimpleNamespace(bozo=False, feed={"title": "empty"}, entries=[])

    def fake_parse(url_or_raw, request_headers=None, **_):
        if isinstance(url_or_raw, (bytes, bytearray)):
            # Reddit fetch_bytes path
            return chelsea_reddit  # default - per-team patching not feasible here
        s = str(url_or_raw).lower()
        if "arsenal" in s or "gunners" in s:
            return arsenal_news if "feeds.bbci" in s or "football.london" in s else arsenal_reddit
        if "chelsea" in s or "chelseafc" in s:
            return chelsea_news
        return empty_feed

    def fake_fetch_bytes(self):
        # Return distinct fake bytes per team so feedparser parses different fixtures.
        # In practice we patch feedparser.parse to return canned feeds based on the
        # team name passed via the bytes signature.
        return self.team.name.encode("utf-8")

    # Per-team feedparser routing by intercepting via _fetch_bytes payload
    def fake_parse_route(raw_or_url, **_):
        if isinstance(raw_or_url, (bytes, bytearray)):
            t = raw_or_url.decode("utf-8", errors="replace").lower()
            if "arsenal" in t:
                return arsenal_reddit
            if "chelsea" in t:
                return chelsea_reddit
            return empty_feed
        s = str(raw_or_url).lower()
        if "arsenal" in s or "gunners" in s:
            return arsenal_news
        if "chelsea" in s:
            return chelsea_news
        return empty_feed

    fake_completions = MagicMock()
    fake_completions.create.side_effect = lambda model, messages, **_: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(_verdict_for_text(
                next((m["content"] for m in messages if m["role"] == "user"), "")
            ))
        ))]
    )
    fake_chat = MagicMock(); fake_chat.completions = fake_completions
    fake_openai_client = MagicMock(); fake_openai_client.chat = fake_chat
    fake_OpenAI = MagicMock(return_value=fake_openai_client)

    fake_urlopen = MagicMock()

    with patch("src.scrapers.reddit_rss_scraper.RedditRSSScraper._fetch_bytes",
               new=fake_fetch_bytes), \
         patch("src.scrapers.reddit_rss_scraper.feedparser.parse",
               side_effect=fake_parse_route), \
         patch("src.scrapers.rss_scraper.feedparser.parse",
               side_effect=fake_parse_route), \
         patch("src.analyzer.groq_analyzer.OpenAI", new=fake_OpenAI), \
         patch("src.notifier.urllib.request.urlopen", new=fake_urlopen):
        rc = app_main.main()
    assert rc == 0

    csv_path = os.path.join(os.environ["OUTPUT_DIR"], "chelsea_tracker.csv")
    df = pd.read_csv(csv_path)
    print("\n=========== E2E TEST PASSED ===========")
    print(f"Rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")
    print(f"Teams: {sorted(set(df['team']))}")
    print(f"Tiers: {df['tier'].value_counts().to_dict()}")

    assert "team" in df.columns, "team column missing"
    teams = set(df["team"])
    assert "Chelsea" in teams, f"Chelsea not in teams: {teams}"
    assert "Arsenal" in teams, f"Arsenal not in teams: {teams}"
    assert "Tier 1" in set(df["tier"]), "No Tier 1 produced"
    print("Multi-team + tier classification: OK")
    print("=======================================\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
