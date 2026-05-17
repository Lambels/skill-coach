"""overview tool — headline counts and totals across the index."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Headline counts and token totals across all indexed skill invocations.

Single-row aggregate over the entire index (or a date window). Tells you
how big the dataset is and what time span it covers, without drilling
into specific skills, sessions, or projects. Cheap — pure DB, no file IO.

Use this when:
    - You need to size up the dataset before drilling in further
    - You want the date range currently covered by the index
    - You want headline token totals across all skills

Don't use this when:
    - You want per-skill ranking → use top_skills
    - You want per-session ranking → use by_session
    - You want USD cost breakdown → use cost_per_skill
    - You want a time-series view → use daily_trend
    - You want detail for one specific skill → use skill_detail

Parameters:
    days (int, optional): Restrict to invocations in the last N days.
        None (default) means all time. Typical values: 7 for a weekly view,
        30 for monthly. The returned first_seen / last_seen timestamps show
        the actual date range covered.

Returns:
    Wrapped envelope { "data": ..., "meta": ... }.

    The data field is a single dict with:
        - invocations: total count of skill invocations in the window
        - distinct_skills: count of unique skill names
        - distinct_sessions: count of unique session IDs
        - distinct_projects: count of unique project cwd paths
        - input_tokens: sum of uncached input tokens
        - output_tokens: sum of model output tokens
        - cache_read_tokens: sum of cache-hit tokens (cheap reads)
        - cache_creation_tokens: sum of cache-write tokens (expensive writes)
        - first_seen: epoch ms of earliest invocation in the window
        - last_seen: epoch ms of latest invocation in the window

    The meta field contains the standard envelope: tool name, params,
    a human-readable window string (e.g. "all time (2026-04-15 → 2026-05-17)"),
    and row_count.

Example:
    overview(days=30)
    # → {"data": {"invocations": 80, "distinct_skills": 15, ...},
    #    "meta": {"tool": "overview", "window": "last 30 days (...)", ...}}

Related tools:
    - top_skills: after sizing up, rank which skills dominate the cost
    - cost_per_skill: translate token sums to USD per skill
    - by_session: find the most expensive individual sessions
    - daily_trend: see how token cost varies day-to-day

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def overview(days: Optional[int] = None) -> dict:
    """Headline counts and totals across the indexed invocations.

    Args:
        days: optional window in days (None = all time)

    Returns:
        Wrapped envelope with the aggregate dict and standard meta.
    """
    with db.connect(get_db_path()) as conn:
        ov = queries.overview(conn, days=days)
    return wrap(
        ov,
        tool="overview",
        params={"days": days},
        window=format_window(days, ov.get("first_seen"), ov.get("last_seen")),
    )
