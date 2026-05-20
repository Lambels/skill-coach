"""get_session_skills tool — ordered list of all skill invocations in a session."""

from __future__ import annotations

from ... import db, queries
from .. import app, get_db_path
from ..result import wrap


_DESCRIPTION = """\
All skill invocations belonging to one session, ordered oldest first.

Use this to reconstruct what happened in a single conversation: which
skills fired, in what order, with what cost. The pointer columns
(`trigger_line_offset`, `start_line_offset`, `end_line_offset`) are
included so the coach can later seek into the JSONL for content.

Questions this tool answers:
    - What was the full skill chain in session X?
    - Where did the cost concentrate within one conversation?
    - Did the same skill repeat? At what intervals?
    - Which skill kicked off a sequence?

Parameters:
    session_id (str): Claude Code session UUID. Available on every row
        returned by `top_skills`, `skill_invocations`, `by_session`, etc.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of dicts ordered by `started_at` ascending,
    each containing:
        - skill_name, invocation_type, session_id, session_file_path
        - started_at, ended_at, duration_ms, n_requests
        - input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
          total_tokens
        - success, cwd, model
        - trigger_line_offset, start_line_offset, end_line_offset

    Empty list if the session_id has no indexed invocations.

Example:
    get_session_skills(session_id="ce043d78-...-...")

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def get_session_skills(session_id: str) -> dict:
    """All skill invocations in one session, oldest first."""
    with db.connect(get_db_path()) as conn:
        rows = queries.session_invocations(conn, session_id)
    return wrap(
        rows,
        tool="get_session_skills",
        params={"session_id": session_id},
    )
