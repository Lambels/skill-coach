"""cost_per_skill tool — USD cost per skill from per-model pricing."""

from __future__ import annotations

from typing import Optional

from ... import db, pricing
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
USD cost per skill, computed from per-model token pricing.

Iterates every invocation in the window, applies the model-specific
rate to each token type (input, output, cache_read, cache_5m,
cache_1h), and sums per skill. Result is sorted by USD cost descending.

Questions this tool answers:
    - How much does each skill cost in USD?
    - Which skills are the most expensive in dollar terms (not just tokens)?
    - What is the total spend in the window?

Parameters:
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of per-skill dicts, ordered by cost_usd
    descending. Each contains:
        - skill_name
        - calls: invocation count
        - cost_usd: USD cost across all invocations of this skill

    To get the total spend across all skills, sum cost_usd across rows.

Note: The same skill_name can have different per-call costs if it was
invoked against different Claude models (Opus vs Sonnet vs Haiku).
This tool collapses those into a single per-skill USD figure.

Example:
    cost_per_skill(days=30)
    # → [{"skill_name": "start-day", "calls": 15, "cost_usd": 17.96}, ...]

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def cost_per_skill(days: Optional[int] = None) -> dict:
    """Per-skill USD cost from per-model pricing.

    Args:
        days: optional window in days
    """
    with db.connect(get_db_path()) as conn:
        rows = pricing.cost_per_skill(conn, days=days)
    return wrap(
        rows,
        tool="cost_per_skill",
        params={"days": days},
        window=format_window(days),
    )
