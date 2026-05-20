"""analyze_volatility tool — coefficient of variation per metric for one skill."""

from __future__ import annotations

from typing import Optional

from ... import db, queries, stats
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Coefficient of variation (stddev / mean) for every standard metric on
one skill. Quick check of how consistent a skill's behaviour is.

CV > 1 means stddev exceeds the mean — heavy spread, likely long tail.
CV ≈ 0 means tight clustering. CV is undefined when mean = 0; reported as
None in that case.

This is the right "should I dig in?" signal before reaching for
`get_distribution` or `find_outliers` — one call answers "which axis is
this skill noisy on?" across all metrics at once.

Questions this tool answers:
    - Is `vault-find-related` consistent or noisy on token cost?
    - Which axis of variability dominates for `daily` — duration, output, or cache?
    - Is `start-day` more stable than `brain-dump`?

Parameters:
    skill_name (str): The skill to analyse.
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field is a dict:
        - skill_name
        - n: sample size
        - metrics: dict keyed by metric name, each entry containing:
            - mean
            - stddev
            - cv: stddev/mean if mean != 0 else None

        Metrics covered: input_tokens, output_tokens, cache_read_tokens,
        cache_creation_tokens, total_tokens, duration_ms, n_requests.

    When n < 2 every cv is None.

Example:
    analyze_volatility(skill_name="vault-find-related", days=30)

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def analyze_volatility(
    skill_name: str,
    days: Optional[int] = None,
) -> dict:
    """Coefficient of variation per standard metric for one skill."""
    metric_data: dict[str, dict] = {}
    sample_size = 0
    with db.connect(get_db_path()) as conn:
        for m in queries.METRIC_EXPRS:
            vs = queries.metric_values(conn, skill_name, m, days=days)
            sample_size = max(sample_size, len(vs))
            mu = stats.mean(vs)
            sd = stats.stddev(vs)
            cv: Optional[float] = (sd / mu) if (mu and len(vs) >= 2) else None
            metric_data[m] = {"mean": mu, "stddev": sd, "cv": cv}

    return wrap(
        {"skill_name": skill_name, "n": sample_size, "metrics": metric_data},
        tool="analyze_volatility",
        params={"skill_name": skill_name, "days": days},
        window=format_window(days),
    )
