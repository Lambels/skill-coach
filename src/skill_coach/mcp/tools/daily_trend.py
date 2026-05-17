"""daily_trend tool — per-day token spend timeline."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Per-day token spend timeline, optionally filtered to one skill.

One row per day in the window. Useful for spotting day-over-day trends,
spikes, or gaps in usage.

Questions this tool answers:
    - How has token spend evolved day-by-day?
    - Are there specific days with unusual spikes?
    - Is one specific skill's usage trending up or down?
    - Which days saw the most invocations?
    - Are there days with no activity?

Parameters:
    days (int): Window in days. Default 30. The result includes one row
        per day, so a large value yields a longer time series.
    skill_name (str, optional): Filter to one specific skill. None = all skills.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of per-day dicts ordered by date ascending:
        - day: "YYYY-MM-DD"
        - calls: invocation count that day
        - input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens

    Days with zero invocations do NOT appear in the result. To detect
    gaps, compare the dates against the expected day range.

Example:
    daily_trend(days=14, skill_name="vault-find-related")
    # → 14-day timeline of vault-find-related activity

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def daily_trend(days: int = 30, skill_name: Optional[str] = None) -> dict:
    """Per-day token spend timeline.

    Args:
        days: window in days (default 30)
        skill_name: optional filter to one skill
    """
    with db.connect(get_db_path()) as conn:
        rows = queries.daily_trend(conn, days=days, skill_name=skill_name)
    return wrap(
        rows,
        tool="daily_trend",
        params={"days": days, "skill_name": skill_name},
        window=format_window(days),
    )
