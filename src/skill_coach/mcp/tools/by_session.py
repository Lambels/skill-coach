"""by_session tool — most expensive sessions by total token cost."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Most expensive sessions ranked by total token cost across all their skill calls.

A "session" is one Claude Code conversation (one JSONL file). This tool
collapses every skill invocation in a session into a single row showing
total spend and skill diversity.

Questions this tool answers:
    - Which sessions burned the most tokens?
    - How many distinct skills ran in each top session?
    - What project was each top session associated with?
    - When did the most expensive sessions happen?

Parameters:
    limit (int): Max sessions to return. Default 20, ranked by total_tokens.
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of session dicts, ordered by total_tokens
    descending. Each contains:
        - session_id: UUID of the session
        - started_at: epoch ms of the session's earliest indexed invocation
        - cwd: project directory the session ran in
        - calls: total skill invocations in this session
        - distinct_skills: number of distinct skill names invoked
        - total_tokens: sum across all invocations in the session

Example:
    by_session(limit=5, days=7)
    # → 5 most expensive sessions in the last week

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def by_session(limit: int = 20, days: Optional[int] = None) -> dict:
    """Most expensive sessions by total token cost.

    Args:
        limit: max rows (default 20)
        days: optional window in days
    """
    with db.connect(get_db_path()) as conn:
        rows = queries.by_session(conn, limit=limit, days=days)
    return wrap(
        rows,
        tool="by_session",
        params={"limit": limit, "days": days},
        window=format_window(days),
    )
