"""
AI analyzer using Groq (free tier, Llama 3.3 70B).

Groq's API is OpenAI-compatible — we use the `openai` SDK and just point its
base_url at Groq. Free tier: 30 req/min, ~14400 req/day. No credit card needed.
Get a key at https://console.groq.com/keys

For each TransferItem we produce:
    - journalist_name: e.g. "Fabrizio Romano", "BBC Sport", "Unknown"
    - transfer_claim:  short factual claim (<=240 chars)
    - tier:            Tier 1 / Tier 2 / Tier 3 / Rumour / Unknown
    - hit_miss:        Hit / Miss / Pending / Unknown
    - confidence:      0.0 - 1.0
    - reasoning:       short rationale (<=400 chars)

Groq supports strict JSON via response_format={"type": "json_object"}.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from openai import OpenAI, APIError, RateLimitError

from ..config import GroqConfig
from ..models import AnalyzedItem, TransferItem

log = logging.getLogger(__name__)


SYSTEM_INSTRUCTION = """You are a senior football journalist analyst specialised in
Premier League transfer reporting. For each news item you receive, return a
structured JSON verdict.

CRITICAL — ONLY classify as Tier 1/2/3/Rumour when the article is genuinely
about a player TRANSFER (a player joining, leaving, being loaned, contract
extension, agreement-in-principle, medical, or formal bid).

Return tier="Unknown" AND hit_miss="Unknown" with confidence<=0.1 for ALL of:
  - Injury reports / player fitness updates / hamstring / surgery
  - Match reports / lineups / starting XI / player ratings
  - Manager press conferences without an explicit transfer claim
  - Tactical analysis / "what we learned" / opinion pieces
  - Fan reaction / social-media chatter without a named source
  - Fixture / scheduling announcements
  - Match-day live blogs

Return verdict fields:

- journalist_name: the named journalist making the claim. Priority order:
    (1) a named REPORTER quoted in the body (look for phrases like
        "according to X", "X reports", "X confirms", "X claims", "as per X",
        "via X", "X tells", "X says", "X exclusive"). Common names to extract
        verbatim when seen: Fabrizio Romano, David Ornstein, Matt Law,
        Jason Burt, Sam Wallace, Nizaar Kinsella, Florian Plettenberg,
        Gianluca Di Marzio, Nicolo Schira, Ben Jacobs, Jacob Steinberg,
        Jamie Jackson, Stuart James, Henry Winter, Chris Wheeler, Simon Stone.
    (2) the `author_byline` field if it contains a real person name.
    (3) the `source` field as outlet fallback ("BBC Sport", "Sky Sports",
        "football.london", "The Telegraph", "GiveMeSport").
  Return "Unknown" only if NONE of (1) (2) (3) yields anything.
- transfer_claim: a single concise factual claim (<= 240 chars), e.g.
  "Chelsea agree £45m fee with Palmeiras for Estevao Willian.".
- tier: reliability of the source/report.
    "Tier 1" = confirmed by club or top-tier reporter (Romano, Ornstein, club
              channel). Concrete deal language ("here we go", medical booked).
    "Tier 2" = reputable national outlet (BBC, Sky Sports, The Athletic) with
              named sourcing but not yet club-confirmed.
    "Tier 3" = tabloid / aggregator-level reporting, "could", "linked".
    "Rumour" = pure speculation, fan-forum chatter, no real sourcing.
    "Unknown" = not enough info to judge.
- hit_miss: "Hit" (story confirmed true), "Miss" (contradicted/fell through),
            "Pending" (still developing), or "Unknown".
- confidence: 0.0 - 1.0 (your confidence in the tier+hit/miss combination).
- reasoning: <= 400 chars rationale.

Return ONLY a JSON object, no prose, no markdown fences.
"""


_DEFAULT_VERDICT: Dict[str, Any] = {
    "journalist_name": "Unknown",
    "transfer_claim": "",
    "tier": "Unknown",
    "hit_miss": "Unknown",
    "confidence": 0.0,
    "reasoning": "",
}


class GroqAnalyzer:
    def __init__(self, cfg: GroqConfig) -> None:
        self.cfg = cfg
        self.client = OpenAI(
            api_key=cfg.api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=cfg.request_timeout,
        )

    def _analyze_one(self, item: TransferItem) -> AnalyzedItem:
        user_payload = {
            "title": item.title,
            "body": item.body[:2000],
            "source": item.source_name,
            "author_byline": item.author or "",
            "url": item.url,
            "published_at": item.published_at.isoformat(),
        }

        verdict = dict(_DEFAULT_VERDICT)
        verdict["transfer_claim"] = item.title[:240]

        try:
            resp = self.client.chat.completions.create(
                model=self.cfg.model,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_output_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {
                        "role": "user",
                        "content": (
                            "Analyze this Chelsea FC transfer news item and respond "
                            "with the JSON verdict object only:\n\n"
                            + json.dumps(user_payload, ensure_ascii=False, indent=2)
                        ),
                    },
                ],
            )
            raw = (resp.choices[0].message.content or "").strip()
            parsed = json.loads(raw)
            for key in _DEFAULT_VERDICT:
                if key in parsed:
                    verdict[key] = parsed[key]
        except RateLimitError as exc:
            log.warning(
                "Groq rate-limit hit on %s — sleeping 2s: %s",
                item.fingerprint(), exc,
            )
            time.sleep(2)
            verdict["reasoning"] = f"Rate-limited: {exc}"
        except json.JSONDecodeError as exc:
            log.warning("Groq returned non-JSON for %s: %s", item.fingerprint(), exc)
            verdict["reasoning"] = f"Non-JSON response: {exc}"
        except (APIError, Exception) as exc:
            log.warning("Groq analysis failed for %s: %s", item.fingerprint(), exc)
            verdict["reasoning"] = f"AI analysis failed: {exc}"

        return AnalyzedItem(
            item=item,
            journalist_name=str(verdict.get("journalist_name", "Unknown"))[:120],
            transfer_claim=str(verdict.get("transfer_claim", ""))[:240],
            tier=str(verdict.get("tier", "Unknown")),
            hit_miss=str(verdict.get("hit_miss", "Unknown")),
            confidence=float(verdict.get("confidence", 0.0) or 0.0),
            reasoning=str(verdict.get("reasoning", ""))[:400],
            analyzed_at=datetime.now(tz=timezone.utc),
        )

    def analyze(self, items: List[TransferItem]) -> List[AnalyzedItem]:
        log.info("Analyzing %d items with Groq (%s)", len(items), self.cfg.model)
        results: List[AnalyzedItem] = []
        for i, it in enumerate(items, 1):
            results.append(self._analyze_one(it))
            # Free tier: 30 req/min ≈ 1 req every 2s. Throttle a touch.
            if i % 25 == 0:
                time.sleep(1)
        return results
