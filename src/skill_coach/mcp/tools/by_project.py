"""by_project tool — per-(project, skill) cross-tab."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Per-(project, skill) cross-tab of invocations and token spend.

One row per unique (cwd, skill_name) pair, ordered by token cost descending.
Lets you see which skills are heavily used in which projects, and where
cross-project skill dispatch occurs.

Questions this tool answers:
    - Which projects use which skills?
    - How much does each (project, skill) pair cost in tokens?
    - Are any skills used across multiple projects?
    - Which project is the dominant cost center?

Parameters:
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of per-(project, skill) dicts, ordered by
    total_tokens descending. Each contains:
        - cwd: project directory path
        - skill_name
        - calls: invocation count for this (project, skill) pair
        - total_tokens

Example:
    by_project(days=30)
    # → cross-tab of project × skill activity over the last 30 days

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def by_project(days: Optional[int] = None) -> dict:
    """Per-(project, skill) breakdown.

    Args:
        days: optional window in days
    """
    with db.connect(get_db_path()) as conn:
        rows = queries.by_project(conn, days=days)
    return wrap(
        rows,
        tool="by_project",
        params={"days": days},
        window=format_window(days),
    )
