"""compare_token_usage tool — numerical delta of two specific invocations."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path, jsonl_seek
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

The response also includes a `skill_md_comparison` block reporting
whether the two invocations ran the same SKILL.md text (via
`skill_md_hash` comparison). When hashes differ, token deltas reflect
BOTH the SKILL.md change AND the call-context change — interpret with
care. When skills differ entirely (different `skill_name`) the response
sets `same_skill = False` and the agent should usually treat the
comparison as exploratory only.

The response also includes an `args_comparison` block carrying both
invocations' raw ARGUMENTS text (fetched on demand from the JSONL via
the recorded line offsets, not stored in the index). The agent is
expected to read both strings and decide whether the difference is
material — `vault-find-related "topic A"` vs `vault-find-related "topic
B"` is technically different args but semantically the same workload;
`/capture "short"` vs `/capture "long detailed thought"` is the
opposite. No automatic verdict — agent judgment only.

Questions this tool answers:
    - How much did this invocation cost vs another invocation of the same skill?
    - Did the new SKILL.md version reduce tokens? (Compare an old + new run.)
    - Why is this run 4× more expensive — which metric drives it?
    - Is the comparison apples-to-apples (same SKILL.md) or confounded?

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
        - skill_md_comparison: dict with:
            - same_skill: bool — are both rows for the same skill_name?
            - same_md: bool|None — do their skill_md_hash values match?
              None when either hash is missing (e.g. failed dispatch).
            - a_hash, b_hash: the two hashes (or null)
            - warning: short string set when same_md is False, otherwise null
        - args_comparison: dict with:
            - a_text, b_text: raw ARGUMENTS strings (or null when no
              ARGUMENTS block / JSONL unreadable)
            - a_size, b_size: byte sizes from the index
            - size_delta: b_size - a_size

    If either row is missing the tool still returns successfully with the
    null in place; `delta`, `skill_md_comparison`, and `args_comparison`
    are omitted.

Reads from: DB + JSONL (seek-by-offset to fetch ARGUMENTS text).
Side effects: none (read-only).

Example:
    compare_token_usage(
        a_session_file_path="/Users/.../session-abc.jsonl", a_start_line_offset=350,
        b_session_file_path="/Users/.../session-abc.jsonl", b_start_line_offset=385,
    )
"""


def _compute_delta(a: dict, b: dict) -> dict:
    out = {}
    for m in _METRICS:
        av = a.get(m, 0) or 0
        bv = b.get(m, 0) or 0
        pct = ((bv - av) / av) if av else None
        out[m] = {"a": av, "b": bv, "abs": bv - av, "pct": pct}
    return out


def _compare_args(a: dict, b: dict) -> dict:
    a_text = jsonl_seek.read_args_at(a["session_file_path"], a["start_line_offset"])
    b_text = jsonl_seek.read_args_at(b["session_file_path"], b["start_line_offset"])
    a_size = a.get("args_size_bytes", 0) or 0
    b_size = b.get("args_size_bytes", 0) or 0
    return {
        "a_text": a_text,
        "b_text": b_text,
        "a_size": a_size,
        "b_size": b_size,
        "size_delta": b_size - a_size,
    }


def _compare_skill_md(a: dict, b: dict) -> dict:
    same_skill = a.get("skill_name") == b.get("skill_name")
    a_hash = a.get("skill_md_hash")
    b_hash = b.get("skill_md_hash")
    if a_hash is None or b_hash is None:
        same_md: Optional[bool] = None
        warning: Optional[str] = (
            "one or both invocations missing skill_md_hash "
            "(failed dispatch?); cannot verify SKILL.md identity"
        )
    else:
        same_md = a_hash == b_hash
        warning = (
            "SKILL.md text differs between invocations — "
            "token delta reflects BOTH skill content AND call context"
            if not same_md
            else None
        )
    if not same_skill:
        warning = (
            "different skill_name — comparison is exploratory only"
            if warning is None
            else warning + "; also different skill_name"
        )
    return {
        "same_skill": same_skill,
        "same_md": same_md,
        "a_hash": a_hash,
        "b_hash": b_hash,
        "warning": warning,
    }


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
        data["skill_md_comparison"] = _compare_skill_md(a, b)
        data["args_comparison"] = _compare_args(a, b)

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
