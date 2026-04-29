"""
Discord webhook notifier for Tier 1 transfer alerts.

Best-effort: a webhook failure logs a warning but never crashes the run.
If DISCORD_WEBHOOK_URL is unset, notifications are silently skipped (so the
pipeline runs fine on machines / forks that don't want alerts).

Configuration via env vars:
    DISCORD_WEBHOOK_URL   the Channel webhook URL (Server Settings -> Integrations)
    NOTIFY_MIN_TIER       "Tier 1" (default), "Tier 2", or "Tier 3"
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import List, Optional

from .models import AnalyzedItem

log = logging.getLogger(__name__)

TIER_EMOJI = {
    "Tier 1": "🟢",
    "Tier 2": "🟡",
    "Tier 3": "🟠",
    "Rumour": "⚪",
    "Unknown": "⚫",
}

HIT_MISS_EMOJI = {
    "Hit": "✅",
    "Miss": "❌",
    "Pending": "⏳",
    "Unknown": "❓",
}

TIER_COLOR = {
    "Tier 1": 0x2ECC71,  # green
    "Tier 2": 0xF1C40F,  # yellow
    "Tier 3": 0xE67E22,  # orange
    "Rumour": 0x95A5A6,  # gray
    "Unknown": 0x7F8C8D,
}

TIER_RANK = {"Tier 1": 1, "Tier 2": 2, "Tier 3": 3, "Rumour": 4, "Unknown": 5}


def _build_embed(item: AnalyzedItem) -> dict:
    title = (
        f"{TIER_EMOJI.get(item.tier, '⚫')} {item.tier}  "
        f"·  {HIT_MISS_EMOJI.get(item.hit_miss, '❓')} {item.hit_miss}"
    )
    return {
        "title": title,
        "description": (item.transfer_claim or item.item.title)[:280],
        "url": item.item.url,
        "color": TIER_COLOR.get(item.tier, 0x95A5A6),
        "fields": [
            {"name": "Journalist", "value": (item.journalist_name or "Unknown")[:120], "inline": True},
            {"name": "Source",     "value": item.item.source_name[:120],               "inline": True},
            {"name": "Confidence", "value": f"{item.confidence:.2f}",                  "inline": True},
        ],
        "footer": {"text": item.item.title[:120]},
        "timestamp": item.analyzed_at.isoformat(),
    }


class DiscordNotifier:
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        min_tier: str = "Tier 1",
    ) -> None:
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "").strip() or None
        self.min_tier = os.getenv("NOTIFY_MIN_TIER", min_tier)
        self.threshold = TIER_RANK.get(self.min_tier, 1)

    def notify(self, items: List[AnalyzedItem]) -> int:
        """Send a Discord embed per qualifying item. Returns # actually sent."""
        if not self.webhook_url:
            log.info("DISCORD_WEBHOOK_URL not set — skipping notifications.")
            return 0

        targets = [it for it in items if TIER_RANK.get(it.tier, 99) <= self.threshold]
        if not targets:
            log.info(
                "No items at >= %s tier in this run (%d analyzed). Nothing to notify.",
                self.min_tier, len(items),
            )
            return 0

        # Cap to avoid Discord rate-limiting (5 msgs/sec/webhook is the docs limit).
        targets = targets[:10]
        sent = 0
        for it in targets:
            payload = {
                "username": "Chelsea Transfer Tracker",
                "avatar_url": "https://upload.wikimedia.org/wikipedia/en/thumb/c/cc/Chelsea_FC.svg/240px-Chelsea_FC.svg.png",
                "embeds": [_build_embed(it)],
            }
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    self.webhook_url,
                    data=data,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        # Discord rejects requests without a recognisable UA
                        # (default Python-urllib/* gets a 403 Forbidden).
                        "User-Agent": (
                            "ChelseaTransferTrackerBot/3.0 "
                            "(+https://github.com/hocco/chelsea-transfer-tracker)"
                        ),
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if 200 <= resp.status < 300:
                        sent += 1
                    else:
                        log.warning("Discord webhook returned %s", resp.status)
            except urllib.error.HTTPError as exc:
                # Capture the response body so we can see *why* Discord rejected.
                try:
                    body = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    body = "<unreadable>"
                log.warning(
                    "Discord HTTP %s for %s: %s | body=%r",
                    exc.code, it.item.fingerprint(), exc.reason, body,
                )
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                log.warning("Discord notification failed for %s: %s", it.item.fingerprint(), exc)

        log.info("Sent %d Discord notification(s) (threshold: %s)", sent, self.min_tier)
        return sent
