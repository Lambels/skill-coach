"""compare_skill_md_versions — unified diff of SKILL.md between two invocations."""

from __future__ import annotations

import difflib

from ... import db, queries
from .. import app, get_db_path, jsonl_seek
from ..result import wrap


_DESCRIPTION = """\
Unified diff of SKILL.md text between two invocations.

Pairs naturally with `compare_token_usage`: when token deltas look weird,
this answers "did the SKILL.md actually change, and how?". Short-circuits
when the two `skill_md_hash` values are identical — no point diffing
known-equal text.

The diff is unified format (3-line context, GNU diff style). For diffs
where SKILL.md content is large, the output can be many KB; the agent
should usually scan structure (which sections changed) rather than read
every line.

Questions this tool answers:
    - Exactly what changed between invocation A and invocation B?
    - Was the edit a tightening, an expansion, or a rewrite?
    - Did the section structure change?

Parameters:
    a_session_file_path (str), a_start_line_offset (int): invocation A.
    b_session_file_path (str), b_start_line_offset (int): invocation B.

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field is a dict:
        - a_skill_name, a_skill_md_hash, a_byte_size
        - b_skill_name, b_skill_md_hash, b_byte_size
        - identical: bool — True iff both hashes present and equal
        - diff: unified diff string (empty when identical or when either
          side could not be read)
        - readable: bool — False when either SKILL.md text could not be
          fetched (missing JSONL, bad offset)

Example:
    compare_skill_md_versions(
        a_session_file_path="/Users/.../sess.jsonl", a_start_line_offset=350,
        b_session_file_path="/Users/.../sess.jsonl", b_start_line_offset=900,
    )

Reads from: DB (lookup) + JSONL (two single-line seeks).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def compare_skill_md_versions(
    a_session_file_path: str,
    a_start_line_offset: int,
    b_session_file_path: str,
    b_start_line_offset: int,
) -> dict:
    """Unified diff of SKILL.md text between two specific invocations."""
    with db.connect(get_db_path()) as conn:
        a_row = queries.invocation_by_pointer(conn, a_session_file_path, a_start_line_offset)
        b_row = queries.invocation_by_pointer(conn, b_session_file_path, b_start_line_offset)

    a_text = jsonl_seek.read_skill_md_at(a_session_file_path, a_start_line_offset)
    b_text = jsonl_seek.read_skill_md_at(b_session_file_path, b_start_line_offset)

    a_hash = a_row.get("skill_md_hash") if a_row else None
    b_hash = b_row.get("skill_md_hash") if b_row else None
    identical = bool(a_hash) and bool(b_hash) and a_hash == b_hash
    readable = a_text is not None and b_text is not None

    diff = ""
    if readable and not identical:
        diff = "".join(difflib.unified_diff(
            a_text.splitlines(keepends=True),
            b_text.splitlines(keepends=True),
            fromfile=f"A ({a_hash or '?'})",
            tofile=f"B ({b_hash or '?'})",
            n=3,
        ))

    data = {
        "a_skill_name":   a_row.get("skill_name") if a_row else None,
        "a_skill_md_hash": a_hash,
        "a_byte_size":    len(a_text.encode("utf-8")) if a_text else 0,
        "b_skill_name":   b_row.get("skill_name") if b_row else None,
        "b_skill_md_hash": b_hash,
        "b_byte_size":    len(b_text.encode("utf-8")) if b_text else 0,
        "identical":      identical,
        "readable":       readable,
        "diff":           diff,
    }
    return wrap(
        data,
        tool="compare_skill_md_versions",
        params={
            "a_session_file_path": a_session_file_path,
            "a_start_line_offset": a_start_line_offset,
            "b_session_file_path": b_session_file_path,
            "b_start_line_offset": b_start_line_offset,
        },
    )
