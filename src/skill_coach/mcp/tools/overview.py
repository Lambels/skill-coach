"""overview tool — headline counts and totals across the index."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


@app.tool()
def overview(days: Optional[int] = None) -> dict:
    """Headline numbers across all indexed skill invocations.

    Returns total invocation count, distinct skills/sessions/projects, and
    token sums (input, output, cache_read, cache_creation). Use this as the
    first call when you need to size up the dataset.

    Args:
        days: optional window restricting to invocations in the last N days
            (None = all time, the default)
    """
    with db.connect(get_db_path()) as conn:
        ov = queries.overview(conn, days=days)
    return wrap(
        ov,
        tool="overview",
        params={"days": days},
        window=format_window(days, ov.get("first_seen"), ov.get("last_seen")),
    )
