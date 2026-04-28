"""
Entry point for the Chelsea FC Transfer News Scraper & AI Analyzer.

Zero-cost stack (v3):
    1. Pull candidate items from Reddit (RSS) and curated news RSS feeds.
    2. Deduplicate against the existing CSV (state-of-the-world).
    3. Send each new item to Groq (free tier, Llama 3.3 70B) for journalist + tier extraction.
    4. Append the analyzed rows to chelsea_tracker.csv (pandas).
    5. Optionally upload the CSV to S3/GCS.

Run as a one-shot job (Docker container scheduled on Harness CI/CD).
"""
from __future__ import annotations

import logging
import os
import sys
from typing import List

from .analyzer import GroqAnalyzer
from .config import load_config
from .models import AnalyzedItem, TransferItem
from .scrapers import NewsRSSScraper, RedditRSSScraper
from .storage import upload, write_csv
from .storage.csv_writer import existing_fingerprints


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    for noisy in ("urllib3", "botocore", "boto3", "openai", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _dedup_against_csv(items: List[TransferItem], csv_path: str) -> List[TransferItem]:
    seen = existing_fingerprints(csv_path)
    return [it for it in items if it.fingerprint() not in seen]


def main() -> int:
    cfg = load_config()
    _setup_logging(cfg.log_level)
    log = logging.getLogger("chelsea-tracker")

    log.info("Chelsea Transfer Tracker starting (zero-cost stack: RSS + Groq)")

    # 1. Scrape (no auth - all public RSS)
    reddit_items = RedditRSSScraper(cfg.reddit_rss, cfg.user_agent).fetch()
    news_items = NewsRSSScraper(cfg.news_rss, cfg.user_agent).fetch()
    all_items: List[TransferItem] = reddit_items + news_items
    log.info("Total candidates from all sources: %d", len(all_items))

    # 2. Dedup against existing CSV (avoid re-spending Groq quota)
    output_dir = os.getenv("OUTPUT_DIR", "/data")
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, cfg.storage.output_filename)

    new_items = _dedup_against_csv(all_items, csv_path)
    log.info("New items to analyze (after CSV dedup): %d", len(new_items))

    if not new_items:
        log.info("Nothing new. Exiting cleanly.")
        if os.path.exists(csv_path):
            upload(csv_path, cfg.storage)
        return 0

    # 3. Analyze with Groq
    analyzer = GroqAnalyzer(cfg.groq)
    analyzed: List[AnalyzedItem] = analyzer.analyze(new_items)

    # 4. Persist (pandas, append-only, schema-stable)
    written = write_csv(csv_path, analyzed)
    log.info("Wrote %d new analyzed rows", written)

    # 5. Push to object storage (or skip in 'local' mode)
    uri = upload(csv_path, cfg.storage)
    if uri:
        log.info("Final artifact available at: %s", uri)

    log.info("Chelsea Transfer Tracker run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
