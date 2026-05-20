"""compare_token_usage tool — numerical delta of two specific invocations."""

from __future__ import annotations

from ... import db, queries
from .. import app, get_db_path
from ..result import wrap


_METRICS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
    "duration_ms",
    "n_requests",
)


_DESCRIPTION = """\
Side-by-side numerical comparison of two specific invocations.

Each invocation is identified by its natural composite key
`(session_file_path, start_line_offset)`. These fields are emitted by
every inventory tool (`skill_invocations`, `top_invocations`,
`get_session_skills`, etc.), so the agent can grab them straight from a
previous result and pass them in here.

Both rows are returned in full plus a `delta` block with absolute and
percent change for every standard metric. Percent change is `None` when
the baseline (A) is zero.

Questions this tool answers:
    - How much did this invocation cost vs another invocation of the same skill?
    - Did the new SKILL.md version reduce tokens? (Compare an old + new run.)
    - Why is this run 4× more expensive — which metric drives it?

Parameters:
    a_session_file_path (str), a_start_line_offset (int): invocation A (baseline).
    b_session_file_path (str), b_start_line_offset (int): invocation B (compared).

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field is a dict:
        - a: full invocation row for A (or null if not found)
        - b: full invocation row for B (or null if not found)
        - delta: dict keyed by metric, each entry containing:
            - a, b: raw values
            - abs: b - a
            - pct: (b - a) / a, or None if a == 0

    If either row is missing the tool still returns successfully with the
    null in place; `delta` is omitted.

Example:
    compare_token_usage(
        a_session_file_path="/Users/.../session-abc.jsonl", a_start_line_offset=350,
        b_session_file_path="/Users/.../session-abc.jsonl", b_start_line_offset=385,
    )

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


def _compute_delta(a: dict, b: dict) -> dict:
    out = {}
    for m in _METRICS:
        av = a.get(m, 0) or 0
        bv = b.get(m, 0) or 0
        pct = ((bv - av) / av) if av else None
        out[m] = {"a": av, "b": bv, "abs": bv - av, "pct": pct}
    return out


@app.tool(description=_DESCRIPTION)
def compare_token_usage(
    a_session_file_path: str,
    a_start_line_offset: int,
    b_session_file_path: str,
    b_start_line_offset: int,
) -> dict:
    """Side-by-side numerical delta of two specific invocations."""
    with db.connect(get_db_path()) as conn:
        a = queries.invocation_by_pointer(conn, a_session_file_path, a_start_line_offset)
        b = queries.invocation_by_pointer(conn, b_session_file_path, b_start_line_offset)

    data: dict = {"a": a, "b": b}
    if a and b:
        data["delta"] = _compute_delta(a, b)

    return wrap(
        data,
        tool="compare_token_usage",
        params={
            "a_session_file_path": a_session_file_path,
            "a_start_line_offset": a_start_line_offset,
            "b_session_file_path": b_session_file_path,
            "b_start_line_offset": b_start_line_offset,
        },
    )
