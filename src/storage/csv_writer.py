"""
Idempotent, append-only CSV writer powered by pandas.

The on-disk file is a normal CSV; we use pandas only for ergonomic dedup and
schema-stable column ordering. We never re-write the whole file - new rows are
appended and ordered by `analyzed_at`.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable, List, Set

import pandas as pd

from ..models import AnalyzedItem

log = logging.getLogger(__name__)

CSV_FIELDS: List[str] = [
    "fingerprint",
    "source",
    "source_name",
    "title",
    "url",
    "author",
    "published_at",
    "journalist_name",
    "transfer_claim",
    "tier",
    "hit_miss",
    "confidence",
    "reasoning",
    "analyzed_at",
]


def existing_fingerprints(path: str) -> Set[str]:
    """Read just the fingerprint column from the existing CSV."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return set()
    try:
        df = pd.read_csv(path, usecols=["fingerprint"], dtype=str)
        return set(df["fingerprint"].dropna().tolist())
    except (ValueError, pd.errors.EmptyDataError) as exc:
        log.warning("Could not read existing fingerprints from %s: %s", path, exc)
        return set()


def write_csv(path: str, items: Iterable[AnalyzedItem]) -> int:
    """Append new analyzed items to the CSV. Returns rows actually written."""
    items = list(items)
    seen = existing_fingerprints(path)

    new_rows = [it.to_row() for it in items if it.item.fingerprint() not in seen]
    if not new_rows:
        log.info("No new rows to write to %s", path)
        return 0

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df = pd.DataFrame(new_rows, columns=CSV_FIELDS)
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0

    df.to_csv(
        path,
        mode="a" if file_exists else "w",
        header=not file_exists,
        index=False,
        encoding="utf-8",
    )
    log.info(
        "Wrote %d new rows to %s (skipped %d duplicates)",
        len(new_rows), path, len(items) - len(new_rows),
    )
    return len(new_rows)


# Backwards-compat alias used in tests / older code paths.
_existing_fingerprints = existing_fingerprints
