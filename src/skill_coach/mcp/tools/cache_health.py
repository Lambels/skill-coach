"""cache_health tool — per-skill cache hit ratio analysis (worst first)."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Per-skill cache hit ratio, ordered worst-first.

A low cache_hit_ratio means a skill repeatedly creates fresh cache rather
than reading from existing cache, which is more expensive (cache_creation
costs 1.25× the input rate; cache_read costs 0.10× the input rate). High
cache_creation with low cache_read = wasted spend.

Questions this tool answers:
    - Which skills have the worst cache hit ratios?
    - Which skills are paying the most in cache_creation tokens
      without recouping it through cache_read?
    - What does the cache profile look like across all skills?

Parameters:
    min_calls (int): Hide skills with fewer than N invocations. Default 5,
        because hit ratios are noisy for low-volume skills.
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of per-skill dicts, ordered by cache_hit_ratio
    ascending (worst-cached skills first). Each contains:
        - skill_name
        - calls
        - total_cache_read, total_cache_creation, total_uncached_input
        - cache_hit_ratio: cache_read / (cache_read + cache_creation + input)
        - avg_cache_read, avg_cache_creation, avg_uncached_input

Example:
    cache_health(min_calls=3, days=30)
    # → skills sorted by cache efficiency, worst first

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def cache_health(min_calls: int = 5, days: Optional[int] = None) -> dict:
    """Per-skill cache analysis, worst hit ratio first.

    Args:
        min_calls: hide skills with fewer than N invocations
        days: optional window in days
    """
    with db.connect(get_db_path()) as conn:
        rows = queries.cache_health(conn, min_calls=min_calls, days=days)
    return wrap(
        rows,
        tool="cache_health",
        params={"min_calls": min_calls, "days": days},
        window=format_window(days),
    )
