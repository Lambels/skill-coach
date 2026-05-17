"""skill_detail tool — full stats for one specific skill."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Full statistical profile for one specific skill.

Returns aggregates (calls, success rate, token sums, distinct sessions
and projects), the slash-vs-tool split, and percentile statistics for
both span duration and request count per span.

Questions this tool answers:
    - What does the full picture for this specific skill look like?
    - How often does this skill succeed vs fail?
    - What is its p50 / p95 duration?
    - How many distinct sessions and projects use it?
    - What is its slash-invoked vs tool-dispatched split?
    - What is its token shape (input / output / cache_read / cache_creation)?

Parameters:
    name (str): The skill name to inspect (e.g. "brain-dump",
        "vault-find-related"). Must match a skill_name in the index exactly.
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": ..., "meta": ... }.

    The data field is a single dict with:
        - skill_name
        - calls: total invocation count
        - total_input, total_output, total_cache_read, total_cache_creation
        - avg_duration_ms, p50_duration_ms, p95_duration_ms
        - avg_requests, p50_requests, p95_requests, total_requests
        - distinct_sessions, distinct_projects
        - success_rate: 0.0 - 1.0
        - slash_calls, tool_calls
        - first_seen, last_seen: epoch ms

    Returns data = None inside the envelope if the skill has zero
    invocations in the window.

Example:
    skill_detail(name="vault-find-related", days=30)
    # → {"data": {"skill_name": "vault-find-related", "calls": 24,
    #             "p95_duration_ms": 102000, ...}, "meta": {...}}

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def skill_detail(name: str, days: Optional[int] = None) -> dict:
    """Full statistical profile for one specific skill.

    Args:
        name: skill name (must match skill_name in the index exactly)
        days: optional window in days (None = all time)
    """
    with db.connect(get_db_path()) as conn:
        d = queries.skill_detail(conn, name, days=days)
    return wrap(
        d,
        tool="skill_detail",
        params={"name": name, "days": days},
        window=format_window(days),
    )
