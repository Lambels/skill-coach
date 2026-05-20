"""find_skill_correlations tool — what skills run before/after this one."""

from __future__ import annotations

from collections import Counter
from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Co-occurrence analysis: what other skills run immediately before or after
the target skill across all sessions in the index.

For each occurrence of the target skill within a session (ordered by
`started_at`), the tool walks `window` steps backwards and forwards and
counts the skill names it sees. Output is two frequency tables, one for
preceding skills and one for following skills, sorted by count descending.

Useful for:
    - Spotting chained calls (e.g. `vault-find-related` is usually followed
      by `vault-write-note`)
    - Detecting orchestration patterns (e.g. `brain-dump` always precedes
      `vault-moc-suggest`)
    - Identifying skills that almost never appear in isolation

Questions this tool answers:
    - Which skills typically run before X?
    - Which skills typically follow X?
    - Does X chain into itself?

Parameters:
    skill_name (str): The target skill.
    window (int): Number of neighbor positions to inspect on each side.
        Default 1 = only immediate neighbors. Larger values inflate counts
        but reveal looser correlations.
    days (int, optional): Restrict to invocations in the last N days.
        None = all time.

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field is a dict:
        - skill_name, window
        - n_occurrences: number of target-skill rows considered
        - preceded_by: list of {skill, count, pct} sorted by count desc
        - followed_by: list of {skill, count, pct} sorted by count desc

    `pct` is count / n_occurrences (so it can exceed 100% when window > 1,
    since each occurrence may see multiple neighbors).

Example:
    find_skill_correlations(skill_name="vault-find-related", window=1)

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


def _neighbour_counts(
    sessions: dict[str, list[dict]],
    skill_name: str,
    window: int,
) -> tuple[Counter, Counter, int]:
    preceded: Counter = Counter()
    followed: Counter = Counter()
    n_occurrences = 0
    for invocs in sessions.values():
        for i, inv in enumerate(invocs):
            if inv["skill_name"] != skill_name:
                continue
            n_occurrences += 1
            for j in range(max(0, i - window), i):
                preceded[invocs[j]["skill_name"]] += 1
            for j in range(i + 1, min(len(invocs), i + window + 1)):
                followed[invocs[j]["skill_name"]] += 1
    return preceded, followed, n_occurrences


@app.tool(description=_DESCRIPTION)
def find_skill_correlations(
    skill_name: str,
    window: int = 1,
    days: Optional[int] = None,
) -> dict:
    """Frequency tables of skills appearing before/after the target skill."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    tf_sql, tf_params = queries.time_filter(days)
    with db.connect(get_db_path()) as conn:
        session_ids = [
            r[0] for r in conn.execute(
                f"""
                SELECT DISTINCT session_id
                FROM skill_invocations
                WHERE skill_name = ? {tf_sql}
                """,
                (skill_name, *tf_params),
            ).fetchall()
        ]
        sessions: dict[str, list[dict]] = {
            sid: queries.session_invocations(conn, sid) for sid in session_ids
        }

    preceded, followed, n = _neighbour_counts(sessions, skill_name, window)
    denom = n or 1

    def _to_list(c: Counter) -> list[dict]:
        return [
            {"skill": name, "count": count, "pct": count / denom}
            for name, count in c.most_common()
        ]

    data = {
        "skill_name": skill_name,
        "window": window,
        "n_occurrences": n,
        "preceded_by": _to_list(preceded),
        "followed_by": _to_list(followed),
    }
    return wrap(
        data,
        tool="find_skill_correlations",
        params={"skill_name": skill_name, "window": window, "days": days},
        window=format_window(days),
    )
