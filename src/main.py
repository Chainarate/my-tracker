"""
Entry point for the Premier League Transfer News Scraper & AI Analyzer.

Zero-cost stack (v4 — multi-team):
    1. For each TeamConfig, pull candidates from its subreddit RSS + news feeds.
    2. Deduplicate against the existing CSV (state-of-the-world).
    3. Send each new item to Groq for journalist + tier extraction.
    4. Append the analyzed rows to the CSV with a `team` column.
    5. Notify Discord on Tier 1 hits (best-effort).
    6. Optionally upload the CSV to S3/GCS.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import List

from .analyzer import GroqAnalyzer
from .config import load_config
from .models import AnalyzedItem, TransferItem
from .notifier import DiscordNotifier
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


def main() -> int:
    cfg = load_config()
    _setup_logging(cfg.log_level)
    log = logging.getLogger("transfer-tracker")

    log.info("Transfer Tracker starting (zero-cost stack: %d teams)", len(cfg.teams))

    # 1. Scrape per-team
    all_items: List[TransferItem] = []
    for team in cfg.teams:
        team_items: List[TransferItem] = []
        team_items += RedditRSSScraper(team, cfg.user_agent).fetch()
        team_items += NewsRSSScraper(team, cfg.user_agent).fetch()
        log.info("[%s] total candidates: %d", team.name, len(team_items))
        all_items += team_items

    log.info("Total candidates across all teams: %d", len(all_items))

    # 2. Dedup against existing CSV (avoid re-spending Groq quota)
    output_dir = os.getenv("OUTPUT_DIR", "/data")
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, cfg.storage.output_filename)

    seen = existing_fingerprints(csv_path)
    new_items = [it for it in all_items if it.fingerprint() not in seen]
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

    # 5. Notify Discord on Tier 1+ hits (best-effort)
    try:
        DiscordNotifier().notify(analyzed)
    except Exception as exc:  # pragma: no cover - belt and suspenders
        log.warning("Notifier raised but pipeline continues: %s", exc)

    # 6. Push to object storage (or skip in 'local' mode)
    uri = upload(csv_path, cfg.storage)
    if uri:
        log.info("Final artifact available at: %s", uri)

    log.info("Transfer Tracker run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
