"""get_distribution tool — percentiles, mean, stddev for one metric on one skill."""

from __future__ import annotations

from typing import Optional

from ... import db, queries, stats
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Percentiles + mean + stddev + min/max for one numeric metric on one skill.

Pulls the raw per-invocation values from the index and runs them through
stdlib statistics. The full sample is read into memory; this is fine for
the metric volumes seen in practice (single skill, ≤ a few thousand rows).

Questions this tool answers:
    - What does the distribution of `output_tokens` look like for `vault-find-related`?
    - Is `duration_ms` long-tailed for `start-day`?
    - Where does the median / p95 sit on `cache_read_tokens` for `daily`?

Parameters:
    skill_name (str): The skill to analyse.
    metric (str): One of:
        "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_creation_tokens",
        "total_tokens"  (= input + output + cache_read + cache_creation),
        "duration_ms", "n_requests"
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field is a dict:
        - skill_name, metric
        - n: sample size
        - mean, stddev
        - min, max
        - p25, p50 (median), p75, p90, p95, p99

    Empty / single-sample cases:
        - n = 0 → all numeric fields are 0.0
        - n = 1 → percentiles all equal that single value; stddev = 0

Example:
    get_distribution(skill_name="vault-find-related", metric="total_tokens", days=30)
    # → {"data": {"skill_name": "vault-find-related", "metric": "total_tokens",
    #             "n": 9, "mean": 264162.0, "p50": 110190.0, "p95": 905104.0, ...}}

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def get_distribution(
    skill_name: str,
    metric: str,
    days: Optional[int] = None,
) -> dict:
    """Distribution stats (percentiles, mean, stddev) for one metric on one skill."""
    if metric not in queries.METRIC_EXPRS:
        raise ValueError(
            f"invalid metric={metric!r}; expected one of {list(queries.METRIC_EXPRS)}"
        )

    with db.connect(get_db_path()) as conn:
        values = queries.metric_values(conn, skill_name, metric, days=days)

    n = len(values)
    if n == 0:
        data = {
            "skill_name": skill_name, "metric": metric, "n": 0,
            "mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0,
            "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0,
        }
    else:
        ps = stats.percentiles(values, [25, 50, 75, 90, 95, 99])
        data = {
            "skill_name": skill_name,
            "metric": metric,
            "n": n,
            "mean": stats.mean(values),
            "stddev": stats.stddev(values),
            "min": min(values),
            "max": max(values),
            "p25": ps[25], "p50": ps[50], "p75": ps[75],
            "p90": ps[90], "p95": ps[95], "p99": ps[99],
        }

    return wrap(
        data,
        tool="get_distribution",
        params={"skill_name": skill_name, "metric": metric, "days": days},
        window=format_window(days),
    )
