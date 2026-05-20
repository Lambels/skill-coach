"""find_outliers tool — invocations more than N stddev from the mean."""

from __future__ import annotations

from typing import Optional

from ... import db, queries, stats
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Per-invocation outliers for one skill / one metric: rows whose value is
more than `threshold` population stddev away from the mean.

For each matching invocation the tool returns the full row (pointers
included) plus the computed z-score, so the coach can pivot straight into
JSONL drilldown via the offset columns.

Questions this tool answers:
    - Which specific runs of `vault-find-related` were token-spike outliers?
    - Are there single invocations of `daily` that dwarf the typical cost?
    - Is `start-day` skewed by a handful of pathological sessions?

Parameters:
    skill_name (str): The skill to scan.
    metric (str): One of:
        "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_creation_tokens",
        "total_tokens", "duration_ms", "n_requests"
        Default "total_tokens".
    threshold (float): Z-score cutoff in stddevs from the mean. Default 2.0.
        Only |z| ≥ threshold is returned. Both high and low outliers qualify.
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field is a dict:
        - skill_name, metric, threshold
        - n: total invocations considered
        - mean, stddev (the baseline used for z-scoring)
        - outliers: list of dicts, each row is one invocation plus:
            - value: the metric value on that row
            - z_score: (value - mean) / stddev, signed
          Sorted by |z_score| descending.

    When n < 2 or stddev == 0 the outliers list is empty (no signal).

Example:
    find_outliers(skill_name="vault-find-related", metric="total_tokens", threshold=2.0)
    # → highlights the 912K-token outlier among the 9 invocations

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def find_outliers(
    skill_name: str,
    metric: str = "total_tokens",
    threshold: float = 2.0,
    days: Optional[int] = None,
) -> dict:
    """Invocations whose chosen metric is > threshold stddev from the mean."""
    if metric not in queries.METRIC_EXPRS:
        raise ValueError(
            f"invalid metric={metric!r}; expected one of {list(queries.METRIC_EXPRS)}"
        )
    if threshold <= 0:
        raise ValueError(f"threshold must be positive, got {threshold}")

    with db.connect(get_db_path()) as conn:
        rows = queries.skill_invocations(conn, skill_name, limit=None, days=days)

    field = "duration_ms" if metric == "duration_ms" else (
        "n_requests" if metric == "n_requests" else metric
    )
    values = [float(r[field]) for r in rows]
    n = len(values)
    mu = stats.mean(values)
    sd = stats.stddev(values)

    outliers: list[dict] = []
    if n >= 2 and sd > 0:
        for r, v in zip(rows, values):
            z = (v - mu) / sd
            if abs(z) >= threshold:
                out = dict(r)
                out["value"] = v
                out["z_score"] = z
                outliers.append(out)
        outliers.sort(key=lambda o: -abs(o["z_score"]))

    data = {
        "skill_name": skill_name,
        "metric": metric,
        "threshold": threshold,
        "n": n,
        "mean": mu,
        "stddev": sd,
        "outliers": outliers,
    }
    return wrap(
        data,
        tool="find_outliers",
        params={"skill_name": skill_name, "metric": metric,
                "threshold": threshold, "days": days},
        window=format_window(days),
    )
