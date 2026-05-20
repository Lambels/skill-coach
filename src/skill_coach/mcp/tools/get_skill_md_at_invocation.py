"""get_skill_md_at_invocation — return the SKILL.md a specific call ran."""

from __future__ import annotations

from ... import db, queries
from .. import app, get_db_path, jsonl_seek
from ..result import wrap


_DESCRIPTION = """\
Return the full SKILL.md text as the model saw it during one specific
invocation, fetched on demand from the originating JSONL.

This is the "what was actually executed?" tool. The DB stores
skill_md_hash for fast version-grouping, but for diffing, content
audits, or "why did this run cost so much?" the agent needs the actual
text. This tool provides it.

The returned text is the SKILL.md prefix only — the trailing
`\\n\\nARGUMENTS: ...` block that Claude Code appends per call is
stripped. For the args, use `compare_token_usage` (which surfaces them
in `args_comparison`) or read directly via the JSONL offsets.

Questions this tool answers:
    - What did SKILL.md look like for invocation X?
    - Is the on-disk SKILL.md the same as what ran?
    - Which version (by content, not just hash) is this row?

Parameters:
    session_file_path (str), start_line_offset (int):
        Composite key for the invocation. Available on every row
        returned by inventory tools.

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field is a dict:
        - skill_name (from index row, when found)
        - skill_md_hash (from index row)
        - skill_md_text: the full SKILL.md text. None when the
          invocation row is missing OR the JSONL line is unreadable
          (e.g. the file was purged after indexing).
        - byte_size: UTF-8 byte length of skill_md_text. 0 when null.

Example:
    get_skill_md_at_invocation(
        session_file_path="/Users/.../session-abc.jsonl",
        start_line_offset=350,
    )

Reads from: DB (lookup) + JSONL (single-line seek).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def get_skill_md_at_invocation(
    session_file_path: str,
    start_line_offset: int,
) -> dict:
    """Full SKILL.md text as the model saw it for one specific invocation."""
    with db.connect(get_db_path()) as conn:
        row = queries.invocation_by_pointer(conn, session_file_path, start_line_offset)

    md_text = jsonl_seek.read_skill_md_at(session_file_path, start_line_offset)
    byte_size = len(md_text.encode("utf-8")) if md_text else 0

    data = {
        "skill_name": row.get("skill_name") if row else None,
        "skill_md_hash": row.get("skill_md_hash") if row else None,
        "skill_md_text": md_text,
        "byte_size": byte_size,
    }
    return wrap(
        data,
        tool="get_skill_md_at_invocation",
        params={
            "session_file_path": session_file_path,
            "start_line_offset": start_line_offset,
        },
    )
