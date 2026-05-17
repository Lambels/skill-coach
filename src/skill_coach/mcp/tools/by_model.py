"""by_model tool — per-Claude-model rollup of invocations and tokens."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Per-Claude-model rollup of invocations and token spend.

One row per Claude model (e.g. claude-sonnet-4-6, claude-opus-4-7) showing
how much each model was used.

Questions this tool answers:
    - How is spend distributed across Claude models?
    - Which model is most used for skills?
    - How does avg token cost differ between models?
    - How many distinct skills used each model?

Parameters:
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of per-model dicts, ordered by total_tokens
    descending. Each contains:
        - model: model identifier (e.g. "claude-sonnet-4-6") or "(unknown)"
        - calls: invocations using this model
        - distinct_skills: number of unique skills that used this model
        - total_tokens, avg_tokens

Example:
    by_model(days=30)
    # → model usage breakdown for the last 30 days

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def by_model(days: Optional[int] = None) -> dict:
    """Per-model rollup.

    Args:
        days: optional window in days
    """
    with db.connect(get_db_path()) as conn:
        rows = queries.by_model(conn, days=days)
    return wrap(
        rows,
        tool="by_model",
        params={"days": days},
        window=format_window(days),
    )
