"""top_invocations tool — single-call outliers, not aggregated."""

from __future__ import annotations

from typing import Optional

from ... import db, pricing, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Single-call outliers across all skills, ordered by the chosen metric.

Unlike top_skills (which aggregates per skill), this returns INDIVIDUAL
invocations — useful for finding "the most expensive single run" across
the entire index. USD cost is computed and added per row.

Questions this tool answers:
    - Which single invocations cost the most tokens / USD?
    - Which individual runs took the longest?
    - Which runs produced the most output tokens?
    - Which spans had the most internal requests?

Parameters:
    by (str): Sort key. One of:
        "tokens" (default) — by total per-invocation tokens descending
        "duration" — by duration_ms descending
        "output" — by output_tokens descending
        "requests" — by n_requests descending
    limit (int): Max rows. Default 20.
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of invocation dicts, sorted by the chosen
    metric. Each contains:
        - invocation_type ("slash_command" or "skill_tool")
        - first_request_id
        - skill_name
        - session_id, session_file_path
        - cwd, started_at, duration_ms, n_requests
        - input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
        - total_tokens (sum)
        - cost_usd: USD cost from per-model pricing
        - success, model
        - trigger_line_offset, start_line_offset, end_line_offset:
          byte offsets into session_file_path for future JSONL drilldown

Example:
    top_invocations(by="tokens", limit=10, days=7)
    # → 10 most expensive single invocations in the last week

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def top_invocations(by: str = "tokens", limit: int = 20, days: Optional[int] = None) -> dict:
    """Single-call outliers across all skills.

    Args:
        by: sort key (tokens, duration, output, requests)
        limit: max rows
        days: optional window in days
    """
    with db.connect(get_db_path()) as conn:
        rows = queries.top_invocations(conn, by=by, limit=limit, days=days)
        for r in rows:
            r["cost_usd"] = pricing.cost_usd(r)
    return wrap(
        rows,
        tool="top_invocations",
        params={"by": by, "limit": limit, "days": days},
        window=format_window(days),
    )
