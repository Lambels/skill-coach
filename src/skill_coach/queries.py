"""Read-only aggregate queries over the skill_invocations index.

Each function takes a sqlite3.Connection and returns either a dict (single row)
or a list of dicts (multi row). No formatting, no JSON, no cost math.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from . import stats


def overview(conn: sqlite3.Connection, days: Optional[int] = None) -> dict:
    """Headline numbers across the whole index (optionally windowed)."""
    tf_sql, tf_params = time_filter(days)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*)                              AS invocations,
            COUNT(DISTINCT skill_name)            AS distinct_skills,
            COUNT(DISTINCT session_id)            AS distinct_sessions,
            COUNT(DISTINCT cwd)                   AS distinct_projects,
            COALESCE(SUM(input_tokens), 0)            AS input_tokens,
            COALESCE(SUM(output_tokens), 0)           AS output_tokens,
            COALESCE(SUM(cache_read_tokens), 0)       AS cache_read_tokens,
            COALESCE(SUM(cache_creation_tokens), 0)   AS cache_creation_tokens,
            MIN(started_at)                       AS first_seen,
            MAX(started_at)                       AS last_seen
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        """,
        tf_params,
    ).fetchone()
    return dict(row) if row else {}


def top_skills(
    conn: sqlite3.Connection,
    by: str = "tokens",
    limit: int = 20,
    days: Optional[int] = None,
    min_calls: int = 1,
) -> list[dict]:
    """Ranked aggregate per skill. `by` ∈ {calls, tokens, avg_tokens, duration, output}."""
    order_by = {
        "calls":       "calls DESC",
        "tokens":      "total_tokens DESC",
        "avg_tokens":  "avg_tokens DESC",
        "duration":    "avg_duration_ms DESC",
        "output":      "total_output DESC",
    }
    if by not in order_by:
        raise ValueError(f"invalid by={by!r}; expected one of {list(order_by)}")

    tf_sql, tf_params = time_filter(days)
    rows = conn.execute(
        f"""
        SELECT
            skill_name,
            COUNT(*)                                                            AS calls,
            SUM(input_tokens + output_tokens
                + cache_read_tokens + cache_creation_tokens)                    AS total_tokens,
            AVG(input_tokens + output_tokens
                + cache_read_tokens + cache_creation_tokens)                    AS avg_tokens,
            AVG(duration_ms)                                                    AS avg_duration_ms,
            AVG(n_requests)                                                     AS avg_requests,
            SUM(output_tokens)                                                  AS total_output,
            SUM(cache_read_tokens)                                              AS total_cache_read,
            SUM(cache_creation_tokens)                                          AS total_cache_creation,
            SUM(input_tokens)                                                   AS total_uncached_input
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        GROUP BY skill_name
        HAVING calls >= ?
        ORDER BY {order_by[by]}
        LIMIT ?
        """,
        (*tf_params, min_calls, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def skill_detail(
    conn: sqlite3.Connection,
    name: str,
    days: Optional[int] = None,
) -> Optional[dict]:
    """Full stats for one skill, including p50/p95 of duration and result size."""
    tf_sql, tf_params = time_filter(days)
    params = (name, *tf_params)

    agg = conn.execute(
        f"""
        SELECT
            COUNT(*)                              AS calls,
            COALESCE(SUM(input_tokens), 0)            AS total_input,
            COALESCE(SUM(output_tokens), 0)           AS total_output,
            COALESCE(SUM(cache_read_tokens), 0)       AS total_cache_read,
            COALESCE(SUM(cache_creation_tokens), 0)   AS total_cache_creation,
            AVG(duration_ms)                      AS avg_duration_ms,
            AVG(n_requests)                       AS avg_requests,
            SUM(n_requests)                       AS total_requests,
            COUNT(DISTINCT session_id)            AS distinct_sessions,
            COUNT(DISTINCT cwd)                   AS distinct_projects,
            COALESCE(SUM(success) * 1.0 / NULLIF(COUNT(*), 0), 0) AS success_rate,
            SUM(CASE WHEN invocation_type = 'slash_command' THEN 1 ELSE 0 END) AS slash_calls,
            SUM(CASE WHEN invocation_type = 'skill_tool'    THEN 1 ELSE 0 END) AS tool_calls,
            MIN(started_at)                       AS first_seen,
            MAX(started_at)                       AS last_seen
        FROM skill_invocations
        WHERE skill_name = ? {tf_sql}
        """,
        params,
    ).fetchone()

    if not agg or agg["calls"] == 0:
        return None

    rows = conn.execute(
        f"""
        SELECT duration_ms, n_requests
        FROM skill_invocations
        WHERE skill_name = ? {tf_sql}
        """,
        params,
    ).fetchall()

    dp = stats.percentiles([r["duration_ms"] for r in rows], [50, 95])
    rp = stats.percentiles([r["n_requests"] for r in rows], [50, 95])

    out = dict(agg)
    out["skill_name"] = name
    out["p50_duration_ms"] = dp[50]
    out["p95_duration_ms"] = dp[95]
    out["p50_requests"] = rp[50]
    out["p95_requests"] = rp[95]
    return out


def skill_invocations(
    conn: sqlite3.Connection,
    name: str,
    limit: Optional[int] = 50,
    days: Optional[int] = None,
) -> list[dict]:
    """Raw list of individual invocations of one skill, newest first.

    `limit=None` returns every matching row (used by analytical tools that
    need the full population, e.g. outlier detection).
    """
    tf_sql, tf_params = time_filter(days)
    limit_sql = "LIMIT ?" if limit is not None else ""
    limit_params: tuple = (limit,) if limit is not None else ()
    rows = conn.execute(
        f"""
        SELECT
            invocation_type, first_request_id, session_id, session_file_path,
            started_at, duration_ms, n_requests,
            input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
            (input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) AS total_tokens,
            success, cwd, model,
            trigger_line_offset, start_line_offset, end_line_offset
        FROM skill_invocations
        WHERE skill_name = ? {tf_sql}
        ORDER BY started_at DESC
        {limit_sql}
        """,
        (name, *tf_params, *limit_params),
    ).fetchall()
    return [dict(r) for r in rows]


def daily_trend(
    conn: sqlite3.Connection,
    days: int = 30,
    skill_name: Optional[str] = None,
) -> list[dict]:
    """One row per day. Optionally filtered to a single skill."""
    skill_clause = "AND skill_name = ?" if skill_name else ""
    skill_params = (skill_name,) if skill_name else ()
    tf_sql, tf_params = time_filter(days)

    rows = conn.execute(
        f"""
        SELECT
            date(started_at / 1000, 'unixepoch') AS day,
            COUNT(*)                              AS calls,
            SUM(input_tokens)                     AS input_tokens,
            SUM(output_tokens)                    AS output_tokens,
            SUM(cache_read_tokens)                AS cache_read_tokens,
            SUM(cache_creation_tokens)            AS cache_creation_tokens
        FROM skill_invocations
        WHERE 1=1 {tf_sql} {skill_clause}
        GROUP BY day
        ORDER BY day
        """,
        (*tf_params, *skill_params),
    ).fetchall()
    return [dict(r) for r in rows]


def by_session(
    conn: sqlite3.Connection,
    limit: int = 20,
    days: Optional[int] = None,
) -> list[dict]:
    """Most expensive sessions by total token cost across all their skill calls."""
    tf_sql, tf_params = time_filter(days)
    rows = conn.execute(
        f"""
        SELECT
            session_id,
            MIN(started_at)                       AS started_at,
            MIN(cwd)                              AS cwd,
            COUNT(*)                              AS calls,
            COUNT(DISTINCT skill_name)            AS distinct_skills,
            SUM(input_tokens + output_tokens
                + cache_read_tokens + cache_creation_tokens) AS total_tokens
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        GROUP BY session_id
        ORDER BY total_tokens DESC
        LIMIT ?
        """,
        (*tf_params, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def by_project(
    conn: sqlite3.Connection,
    days: Optional[int] = None,
) -> list[dict]:
    """Per-(project, skill) breakdown."""
    tf_sql, tf_params = time_filter(days)
    rows = conn.execute(
        f"""
        SELECT
            cwd,
            skill_name,
            COUNT(*)                              AS calls,
            SUM(input_tokens + output_tokens
                + cache_read_tokens + cache_creation_tokens) AS total_tokens
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        GROUP BY cwd, skill_name
        ORDER BY total_tokens DESC
        """,
        tf_params,
    ).fetchall()
    return [dict(r) for r in rows]


def by_model(
    conn: sqlite3.Connection,
    days: Optional[int] = None,
) -> list[dict]:
    """Per-model rollup."""
    tf_sql, tf_params = time_filter(days)
    rows = conn.execute(
        f"""
        SELECT
            COALESCE(model, '(unknown)')          AS model,
            COUNT(*)                              AS calls,
            COUNT(DISTINCT skill_name)            AS distinct_skills,
            SUM(input_tokens + output_tokens
                + cache_read_tokens + cache_creation_tokens) AS total_tokens,
            AVG(input_tokens + output_tokens
                + cache_read_tokens + cache_creation_tokens) AS avg_tokens
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        GROUP BY model
        ORDER BY total_tokens DESC
        """,
        tf_params,
    ).fetchall()
    return [dict(r) for r in rows]


def cache_health(
    conn: sqlite3.Connection,
    min_calls: int = 5,
    days: Optional[int] = None,
) -> list[dict]:
    """Per-skill cache analysis. Lower cache_hit_ratio = more expensive."""
    tf_sql, tf_params = time_filter(days)
    rows = conn.execute(
        f"""
        SELECT
            skill_name,
            COUNT(*)                              AS calls,
            SUM(cache_read_tokens)                AS total_cache_read,
            SUM(cache_creation_tokens)            AS total_cache_creation,
            SUM(input_tokens)                     AS total_uncached_input,
            CAST(SUM(cache_read_tokens) AS REAL) / NULLIF(
                SUM(cache_read_tokens + cache_creation_tokens + input_tokens), 0
            )                                     AS cache_hit_ratio,
            AVG(cache_read_tokens)                AS avg_cache_read,
            AVG(cache_creation_tokens)            AS avg_cache_creation,
            AVG(input_tokens)                     AS avg_uncached_input
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        GROUP BY skill_name
        HAVING calls >= ?
        ORDER BY cache_hit_ratio ASC
        """,
        (*tf_params, min_calls),
    ).fetchall()
    return [dict(r) for r in rows]


def all_skills_full(
    conn: sqlite3.Connection,
    days: Optional[int] = None,
    min_calls: int = 1,
    name_filter: Optional[str] = None,
    invocation_type: Optional[str] = None,
) -> list[dict]:
    """One row per skill with every aggregate column the `skills` CLI surfaces.

    Cost is NOT included here — caller merges in pricing.cost_per_skill(),
    since cost depends on per-row model rates that don't aggregate cleanly in SQL.
    """
    tf_sql, tf_params = time_filter(days)
    extra_sql = ""
    extra_params: tuple = ()
    if name_filter:
        extra_sql += " AND skill_name LIKE ?"
        extra_params = (*extra_params, f"%{name_filter}%")
    if invocation_type:
        if invocation_type not in ("slash_command", "skill_tool"):
            raise ValueError(
                f"invalid invocation_type={invocation_type!r}; "
                "expected 'slash_command' or 'skill_tool'"
            )
        extra_sql += " AND invocation_type = ?"
        extra_params = (*extra_params, invocation_type)

    rows = conn.execute(
        f"""
        SELECT
            skill_name,
            COUNT(*)                              AS calls,
            SUM(input_tokens + output_tokens
                + cache_read_tokens + cache_creation_tokens) AS total_tokens,
            AVG(input_tokens + output_tokens
                + cache_read_tokens + cache_creation_tokens) AS avg_tokens,
            AVG(duration_ms)                      AS avg_duration_ms,
            AVG(n_requests)                       AS avg_requests,
            SUM(output_tokens)                    AS total_output,
            SUM(input_tokens)                     AS total_uncached_input,
            SUM(cache_read_tokens)                AS total_cache_read,
            SUM(cache_creation_tokens)            AS total_cache_creation,
            CAST(SUM(cache_read_tokens) AS REAL) / NULLIF(
                SUM(cache_read_tokens + cache_creation_tokens + input_tokens), 0
            )                                     AS cache_hit_ratio,
            SUM(CASE WHEN invocation_type = 'slash_command' THEN 1 ELSE 0 END) AS slash_calls,
            SUM(CASE WHEN invocation_type = 'skill_tool'    THEN 1 ELSE 0 END) AS tool_calls
        FROM skill_invocations
        WHERE 1=1 {tf_sql} {extra_sql}
        GROUP BY skill_name
        HAVING calls >= ?
        ORDER BY total_tokens DESC
        """,
        (*tf_params, *extra_params, min_calls),
    ).fetchall()
    return [dict(r) for r in rows]


def top_invocations(
    conn: sqlite3.Connection,
    by: str = "tokens",
    limit: int = 20,
    days: Optional[int] = None,
) -> list[dict]:
    """Single-call outliers (no aggregation). `by` ∈ {tokens, duration, output, requests}."""
    order_by = {
        "tokens":   "(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) DESC",
        "duration": "duration_ms DESC",
        "output":   "output_tokens DESC",
        "requests": "n_requests DESC",
    }
    if by not in order_by:
        raise ValueError(f"invalid by={by!r}; expected one of {list(order_by)}")

    tf_sql, tf_params = time_filter(days)
    rows = conn.execute(
        f"""
        SELECT
            invocation_type, first_request_id, skill_name, session_id, session_file_path,
            cwd, started_at, duration_ms, n_requests,
            input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
            (input_tokens + output_tokens
             + cache_read_tokens + cache_creation_tokens) AS total_tokens,
            success, model,
            trigger_line_offset, start_line_offset, end_line_offset
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        ORDER BY {order_by[by]}
        LIMIT ?
        """,
        (*tf_params, limit),
    ).fetchall()
    return [dict(r) for r in rows]


METRIC_EXPRS: dict[str, str] = {
    "input_tokens":          "input_tokens",
    "output_tokens":         "output_tokens",
    "cache_read_tokens":     "cache_read_tokens",
    "cache_creation_tokens": "cache_creation_tokens",
    "total_tokens":          "(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens)",
    "duration_ms":           "duration_ms",
    "n_requests":            "n_requests",
}


def metric_values(
    conn: sqlite3.Connection,
    skill_name: str,
    metric: str,
    days: Optional[int] = None,
) -> list[float]:
    """Raw per-invocation values for one metric on one skill. Used by analytical helpers."""
    if metric not in METRIC_EXPRS:
        raise ValueError(f"invalid metric={metric!r}; expected one of {list(METRIC_EXPRS)}")
    tf_sql, tf_params = time_filter(days)
    rows = conn.execute(
        f"""
        SELECT {METRIC_EXPRS[metric]} AS v
        FROM skill_invocations
        WHERE skill_name = ? {tf_sql}
        """,
        (skill_name, *tf_params),
    ).fetchall()
    return [float(r["v"]) for r in rows]


def session_invocations(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """Every skill invocation in one session, oldest first."""
    rows = conn.execute(
        """
        SELECT
            invocation_type, skill_name, session_id, session_file_path,
            started_at, ended_at, duration_ms, n_requests,
            input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
            (input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) AS total_tokens,
            success, cwd, model,
            trigger_line_offset, start_line_offset, end_line_offset
        FROM skill_invocations
        WHERE session_id = ?
        ORDER BY started_at ASC
        """,
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def invocation_by_pointer(
    conn: sqlite3.Connection,
    session_file_path: str,
    start_line_offset: int,
) -> Optional[dict]:
    """Single invocation row, located by its natural composite key."""
    row = conn.execute(
        """
        SELECT
            invocation_type, skill_name, session_id, session_file_path,
            started_at, ended_at, duration_ms, n_requests,
            input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
            (input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) AS total_tokens,
            success, cwd, model, first_request_id, service_tier,
            trigger_line_offset, start_line_offset, end_line_offset
        FROM skill_invocations
        WHERE session_file_path = ? AND start_line_offset = ?
        """,
        (session_file_path, start_line_offset),
    ).fetchone()
    return dict(row) if row else None


def time_filter(days: Optional[int]) -> tuple[str, tuple]:
    if days is None:
        return "", ()
    cutoff_ms = int((time.time() - days * 86400) * 1000)
    return "AND started_at >= ?", (cutoff_ms,)


def _smoke(db_path: str = "/tmp/csm-smoke.db") -> None:
    from . import db

    with db.connect(db_path) as conn:
        print("=== overview ===")
        ov = overview(conn)
        for k, v in ov.items():
            print(f"  {k:<24} {v}")

        print("\n=== top_skills(by='tokens', limit=10) ===")
        for r in top_skills(conn, by="tokens", limit=10):
            print(f"  {r['calls']:>4} {r['skill_name']:<25}"
                  f" total={r['total_tokens']:>10,}"
                  f" avg={r['avg_tokens']:>8,.0f}"
                  f" avg_ms={r['avg_duration_ms']:>5.0f}")

        print("\n=== top_skills(by='avg_tokens', limit=10) ===")
        for r in top_skills(conn, by="avg_tokens", limit=10, min_calls=2):
            print(f"  {r['calls']:>4} {r['skill_name']:<25}"
                  f" avg={r['avg_tokens']:>10,.0f}")

        print("\n=== skill_detail('vault-find-related') ===")
        d = skill_detail(conn, "vault-find-related")
        if d:
            for k, v in d.items():
                print(f"  {k:<24} {v}")

        print("\n=== daily_trend(days=30) — last 5 days ===")
        for r in daily_trend(conn, days=30)[-5:]:
            print(f"  {r['day']}  calls={r['calls']:<3}"
                  f"  out={r['output_tokens']:>6}"
                  f"  cache_r={r['cache_read_tokens']:>9}")

        print("\n=== by_session(limit=5) ===")
        for r in by_session(conn, limit=5):
            print(f"  {r['session_id'][:8]}  calls={r['calls']:<3}"
                  f"  skills={r['distinct_skills']:<2}"
                  f"  tokens={r['total_tokens']:>10,}")

        print("\n=== by_project ===")
        for r in by_project(conn)[:8]:
            cwd = (r['cwd'] or '')[-30:]
            print(f"  {cwd:<30}  {r['skill_name']:<20}  calls={r['calls']:<3}"
                  f"  tokens={r['total_tokens']:>10,}")

        print("\n=== by_model ===")
        for r in by_model(conn):
            print(f"  {r['model']:<30}  calls={r['calls']:<3}"
                  f"  total={r['total_tokens']:>12,}"
                  f"  avg={r['avg_tokens']:>8,.0f}")

        print("\n=== cache_health(min_calls=3) — worst first ===")
        for r in cache_health(conn, min_calls=3):
            ratio = r['cache_hit_ratio'] or 0
            print(f"  {r['skill_name']:<25}  calls={r['calls']:<3}"
                  f"  hit_ratio={ratio:.3f}")

        print("\n=== top_invocations(by='tokens', limit=5) ===")
        for r in top_invocations(conn, by="tokens", limit=5):
            print(f"  {r['invocation_type']:<14} {r['skill_name']:<25}"
                  f"  tokens={r['total_tokens']:>10,}"
                  f"  trigger@{r['trigger_line_offset']}  in {Path(r['session_file_path']).name[:8]}")


if __name__ == "__main__":
    import sys
    _smoke(sys.argv[1] if len(sys.argv) >= 2 else "/tmp/csm-smoke.db")
