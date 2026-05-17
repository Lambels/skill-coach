"""top_skills tool — ranked aggregate per skill, with rich columns."""

from __future__ import annotations

from typing import Optional

from ... import db, pricing, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_SORT_KEYS = {
    "tokens":     lambda r: -(r.get("total_tokens") or 0),
    "cost":       lambda r: -(r.get("cost_usd") or 0),
    "calls":      lambda r: -(r.get("calls") or 0),
    "avg_tokens": lambda r: -(r.get("avg_tokens") or 0),
    "duration":   lambda r: -(r.get("avg_duration_ms") or 0),
    "output":     lambda r: -(r.get("total_output") or 0),
    "requests":   lambda r: -(r.get("avg_requests") or 0),
    "hit_ratio":  lambda r: (r.get("cache_hit_ratio") or 0),  # ascending: worst first
}


_DESCRIPTION = """\
Ranked per-skill aggregate. One row per skill with full statistics.

Returns every skill present in the window, with token sums, call counts,
USD cost, cache hit ratio, average duration, average request count, and a
slash-vs-tool invocation split. Sorted by the chosen metric.

Questions this tool answers:
    - Which skills cost the most tokens / the most USD?
    - Which skills are most frequently invoked?
    - Which skills have the worst cache hit ratio?
    - Which skills are slowest on average?
    - Which skills generate the most output?
    - How are slash-invoked vs tool-dispatched calls distributed per skill?

Parameters:
    by (str): Sort key. One of:
        "tokens" (default) — by total_tokens descending
        "cost" — by USD cost descending
        "calls" — by invocation count descending
        "avg_tokens" — by mean tokens per invocation descending
        "duration" — by mean span duration descending
        "output" — by total output_tokens descending
        "requests" — by mean request count per span descending
        "hit_ratio" — by cache_hit_ratio ascending (worst cache first)
    limit (int, optional): Max rows to return. None means no limit
        (return every skill). Default 50.
    days (int, optional): Restrict window to last N days. None = all time.
    min_calls (int): Hide skills with fewer than N invocations. Default 1.
    name_filter (str, optional): Substring match against skill_name.
    invocation_type (str, optional): "slash_command" or "skill_tool" only.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of dicts, one per skill, each containing:
        - skill_name
        - calls: total invocation count
        - total_tokens, avg_tokens
        - total_output, total_uncached_input, total_cache_read, total_cache_creation
        - avg_duration_ms, avg_requests
        - cache_hit_ratio: cache_read / (cache_read + cache_creation + input)
        - slash_calls, tool_calls: invocation_type split
        - cost_usd: USD cost from per-model pricing

Example:
    top_skills(by="cost", limit=5, days=30)
    # → returns the 5 most expensive skills in the last 30 days

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def top_skills(
    by: str = "tokens",
    limit: Optional[int] = 50,
    days: Optional[int] = None,
    min_calls: int = 1,
    name_filter: Optional[str] = None,
    invocation_type: Optional[str] = None,
) -> dict:
    """Ranked per-skill aggregate with rich columns."""
    if by not in _SORT_KEYS:
        raise ValueError(f"invalid by={by!r}; expected one of {list(_SORT_KEYS)}")
    if invocation_type and invocation_type not in ("slash_command", "skill_tool"):
        raise ValueError(
            f"invalid invocation_type={invocation_type!r}; "
            "expected 'slash_command' or 'skill_tool'"
        )

    with db.connect(get_db_path()) as conn:
        rows = queries.all_skills_full(
            conn, days=days, min_calls=min_calls,
            name_filter=name_filter, invocation_type=invocation_type,
        )
        cost_by_skill = {c["skill_name"]: c["cost_usd"] for c in pricing.cost_per_skill(conn, days=days)}

    for r in rows:
        r["cost_usd"] = cost_by_skill.get(r["skill_name"], 0.0)

    rows.sort(key=_SORT_KEYS[by])
    if limit is not None:
        rows = rows[:limit]

    return wrap(
        rows,
        tool="top_skills",
        params={"by": by, "limit": limit, "days": days, "min_calls": min_calls,
                "name_filter": name_filter, "invocation_type": invocation_type},
        window=format_window(days),
    )
