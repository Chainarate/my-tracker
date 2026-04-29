"""
Daily Discord digest of Premier League transfer activity.

Reads data/chelsea_tracker.csv, filters items analyzed in the last 24h,
computes a tight summary, and posts ONE blue embed to the Discord webhook.

Designed to run from a separate GitHub Actions cron — once per day, e.g.
09:00 UTC = 16:00 Asia/Bangkok.

Env vars (same as the main scraper):
    DISCORD_WEBHOOK_URL   Optional. If unset, prints the digest to stdout only.
    DIGEST_LOOKBACK_HOURS Optional. Default 24.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

log = logging.getLogger("digest")
logging.basicConfig(level="INFO", format="%(asctime)s | %(levelname)s | %(message)s")

WEBHOOK_USERNAME = "Premier League Transfer Tracker"
WEBHOOK_AVATAR = "https://abs.twimg.com/emoji/v2/72x72/1f4f0.png"
TEAM_EMOJI = "⚽"


def _read_rows(path: Path) -> List[dict]:
    if not path.exists():
        log.error("CSV not found at %s", path)
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _within_lookback(row: dict, cutoff: datetime) -> bool:
    ts = row.get("analyzed_at") or ""
    try:
        return datetime.fromisoformat(ts) >= cutoff
    except ValueError:
        return False


def _build_embed(rows: List[dict], lookback_h: int, total_csv_rows: int) -> dict:
    """Build a single Discord embed describing the lookback window."""
    n = len(rows)
    teams = Counter(r.get("team", "") for r in rows)
    tiers = Counter(r.get("tier", "") for r in rows)
    journalists = Counter(
        r.get("journalist_name", "")
        for r in rows
        if r.get("journalist_name") and r.get("journalist_name", "").lower() != "unknown"
    )

    tier1_lines = []
    for r in rows:
        if r.get("tier") == "Tier 1" and r.get("hit_miss") in ("Hit", "Pending"):
            tier1_lines.append(
                f"• **{r.get('team', '?')}** — {r.get('transfer_claim') or r.get('title', '')[:90]} "
                f"_(by {r.get('journalist_name', 'Unknown')})_"
            )
            if len(tier1_lines) >= 5:
                break

    by_team = " · ".join(
        f"{t} {c}" for t, c in teams.most_common() if t
    ) or "(none)"
    by_tier = " · ".join(f"{t} {c}" for t, c in tiers.most_common() if t) or "(none)"
    top_journos = " · ".join(f"{j} ({c})" for j, c in journalists.most_common(5)) or "(none)"

    today = datetime.now(timezone.utc).strftime("%d %b %Y")

    description_parts = [
        f"**{n}** transfer items analyzed in last {lookback_h}h "
        f"(database total: {total_csv_rows}).",
        "",
        f"**By tier:** {by_tier}",
        f"**By team:** {by_team}",
    ]
    if top_journos != "(none)":
        description_parts.append(f"**Top journalists:** {top_journos}")
    if tier1_lines:
        description_parts.append("")
        description_parts.append("**🟢 Tier 1 of the day:**")
        description_parts.extend(tier1_lines)
    description = "\n".join(description_parts)[:4000]

    return {
        "title": f"📊 Daily Transfer Digest — {today}",
        "description": description,
        "color": 0x3498DB,  # blue
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Auto-generated · Premier League Transfer Tracker"},
    }


def _post(webhook_url: str, embed: dict) -> bool:
    payload = {
        "username": WEBHOOK_USERNAME,
        "avatar_url": WEBHOOK_AVATAR,
        "embeds": [embed],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "PremierLeagueTransferTrackerDigest/1.0 (+github)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        log.warning("Discord HTTP %s: %s | body=%r", exc.code, exc.reason, body)
        return False
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        log.warning("Discord post failed: %s", exc)
        return False


def main() -> int:
    csv_path = Path(os.getenv("DIGEST_CSV", "data/chelsea_tracker.csv"))
    lookback_h = int(os.getenv("DIGEST_LOOKBACK_HOURS", "24"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_h)

    all_rows = _read_rows(csv_path)
    recent = [r for r in all_rows if _within_lookback(r, cutoff)]
    log.info("Lookback %dh: %d/%d rows match", lookback_h, len(recent), len(all_rows))

    if not recent:
        log.info("No recent activity — skipping digest post (silent OK).")
        return 0

    embed = _build_embed(recent, lookback_h, total_csv_rows=len(all_rows))
    print(json.dumps(embed, indent=2))

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        log.info("DISCORD_WEBHOOK_URL not set — embed printed above only.")
        return 0

    ok = _post(webhook_url, embed)
    log.info("Discord post: %s", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
