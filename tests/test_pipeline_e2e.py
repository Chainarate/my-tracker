"""
End-to-end pipeline test with mocked external services.
Verifies that scrapers -> Groq analyzer -> CSV writer -> object_store all
wire up correctly without needing a real Groq key or live RSS access.

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

# Make `src.*` importable when running standalone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rss_entry(title: str, summary: str, link: str, author: str = "Author"):
    return {
        "title": title,
        "summary": summary,
        "link": link,
        "id": link,
        "author": author,
        "published_parsed": datetime.now(tz=timezone.utc).timetuple(),
    }


def _verdict_for_text(text: str) -> dict:
    if "Estevao" in text or "here we go" in text.lower():
        return {
            "journalist_name": "Fabrizio Romano",
            "transfer_claim": "Chelsea sign Estevao Willian from Palmeiras.",
            "tier": "Tier 1",
            "hit_miss": "Pending",
            "confidence": 0.92,
            "reasoning": "Romano 'here we go' confirmation.",
        }
    if "shock move" in text.lower() or "linked" in text.lower():
        return {
            "journalist_name": "Unknown",
            "transfer_claim": "Tabloid links Chelsea to unnamed striker.",
            "tier": "Rumour",
            "hit_miss": "Unknown",
            "confidence": 0.20,
            "reasoning": "No named source, tabloid framing.",
        }
    return {
        "journalist_name": "BBC Sport",
        "transfer_claim": "Chelsea complete signing of new midfielder.",
        "tier": "Tier 2",
        "hit_miss": "Hit",
        "confidence": 0.80,
        "reasoning": "Reputable national outlet, completion language.",
    }


def main() -> int:
    os.environ.update({
        "GROQ_API_KEY": "fake_key",
        "STORAGE_BACKEND": "local",
        "STORAGE_BUCKET": "",
        "OUTPUT_DIR": tempfile.mkdtemp(prefix="chelsea_e2e_"),
        "LOG_LEVEL": "INFO",
    })

    from src import main as app_main  # noqa: E402

    # ---- Fake feedparser responses ------------------------------------------
    reddit_feed = SimpleNamespace(
        bozo=False,
        feed={"title": "r/chelseafc"},
        entries=[
            _rss_entry(
                "[Tier 1] Romano: Chelsea sign Estevao here we go!",
                "Official Chelsea statement expected within 24 hours.",
                "https://reddit.com/r/chelseafc/comments/abc1",
                author="/u/test_user",
            ),
            _rss_entry(
                "Chelsea linked with shock move for unknown striker",
                "Tabloid speculation only.",
                "https://reddit.com/r/chelseafc/comments/abc2",
            ),
            _rss_entry(  # filtered (no transfer keywords)
                "Match thread: Chelsea vs Arsenal",
                "Live match thread.",
                "https://reddit.com/r/chelseafc/comments/abc3",
            ),
        ],
    )

    news_feed = SimpleNamespace(
        bozo=False,
        feed={"title": "BBC Sport - Chelsea"},
        entries=[
            _rss_entry(
                "Chelsea complete signing of new midfielder",
                "Chelsea have officially completed the signing.",
                "https://example.com/chelsea-signing",
            ),
            _rss_entry(  # filtered (no 'chelsea' keyword)
                "Arsenal beat Spurs 2-0",
                "North London derby report.",
                "https://example.com/arsenal",
            ),
        ],
    )

    def fake_parse(url_or_raw, request_headers=None, **_):
        # Reddit scraper passes raw bytes; news scraper passes a URL string.
        if isinstance(url_or_raw, (bytes, bytearray)):
            return reddit_feed
        return news_feed

    def fake_fetch_bytes(self):
        return b"<irrelevant>mocked</irrelevant>"

    # ---- Fake Groq (OpenAI-compatible) client -------------------------------
    def fake_create(model, messages, **kwargs):
        user_text = next(
            (m["content"] for m in messages if m["role"] == "user"),
            "",
        )
        verdict = _verdict_for_text(user_text)
        msg = SimpleNamespace(content=json.dumps(verdict))
        choice = SimpleNamespace(message=msg)
        return SimpleNamespace(choices=[choice])

    fake_completions = MagicMock()
    fake_completions.create.side_effect = fake_create
    fake_chat = MagicMock()
    fake_chat.completions = fake_completions
    fake_openai_client = MagicMock()
    fake_openai_client.chat = fake_chat
    fake_OpenAI = MagicMock(return_value=fake_openai_client)

    # ---- Run pipeline -------------------------------------------------------
    with patch(
        "src.scrapers.reddit_rss_scraper.RedditRSSScraper._fetch_bytes",
        new=fake_fetch_bytes,
    ), patch(
        "src.scrapers.reddit_rss_scraper.feedparser.parse",
        side_effect=fake_parse,
    ), patch(
        "src.scrapers.rss_scraper.feedparser.parse",
        side_effect=fake_parse,
    ), patch(
        "src.analyzer.groq_analyzer.OpenAI",
        new=fake_OpenAI,
    ):
        rc = app_main.main()

    assert rc == 0, f"Pipeline exit code was {rc}"

    csv_path = os.path.join(os.environ["OUTPUT_DIR"], "chelsea_tracker.csv")
    assert os.path.exists(csv_path), f"CSV not created at {csv_path}"

    df = pd.read_csv(csv_path)
    print("\n=========== E2E TEST PASSED ===========")
    print(f"CSV: {csv_path}")
    print(f"Rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")

    assert len(df) >= 3, f"Expected >=3 rows, got {len(df)}"

    required_cols = {"journalist_name", "transfer_claim", "tier", "hit_miss", "confidence"}
    assert required_cols.issubset(set(df.columns)), \
        f"Missing required columns: {required_cols - set(df.columns)}"

    tier_set = set(df["tier"].tolist())
    assert {"Tier 1", "Rumour"}.issubset(tier_set), f"Missing expected tiers: {tier_set}"
    assert "Fabrizio Romano" in set(df["journalist_name"].tolist()), \
        "Journalist extraction failed"

    for _, row in df.iterrows():
        print(f"  [{row['tier']:<7}] {row['hit_miss']:<8} "
              f"by {row['journalist_name']:<20} | {row['title'][:50]}")

    # ---- Idempotency check --------------------------------------------------
    initial = len(df)
    with patch(
        "src.scrapers.reddit_rss_scraper.RedditRSSScraper._fetch_bytes",
        new=fake_fetch_bytes,
    ), patch(
        "src.scrapers.reddit_rss_scraper.feedparser.parse",
        side_effect=fake_parse,
    ), patch(
        "src.scrapers.rss_scraper.feedparser.parse",
        side_effect=fake_parse,
    ), patch(
        "src.analyzer.groq_analyzer.OpenAI",
        new=fake_OpenAI,
    ):
        rc2 = app_main.main()

    df2 = pd.read_csv(csv_path)
    assert rc2 == 0
    assert len(df2) == initial, (
        f"Idempotency broken: {len(df2)} rows after rerun (was {initial})"
    )
    print(f"Idempotency check: rerun added 0 rows (still {initial}). OK.")
    print("=======================================\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
