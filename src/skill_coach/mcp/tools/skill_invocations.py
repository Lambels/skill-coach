"""skill_invocations tool — raw list of one skill's individual invocations."""

from __future__ import annotations

from typing import Optional

from ... import db, queries
from .. import app, get_db_path
from ..result import format_window, wrap


_DESCRIPTION = """\
Raw list of individual invocations for one skill, newest first.

Each row is one execution of the skill (one span) with its own tokens,
duration, request count, session, and outcome. Includes JSONL line offsets
so a follow-up drilldown tool can seek into the raw conversation.

Questions this tool answers:
    - What individual runs of this skill exist, and what did each cost?
    - When was the most recent invocation?
    - Which sessions invoked this skill?
    - Were any invocations failures?
    - What were the slowest / largest individual runs?

Parameters:
    name (str): The skill name to enumerate (e.g. "brain-dump").
    limit (int): Max rows to return. Default 50, newest first.
    days (int, optional): Restrict window to last N days. None = all time.

Returns:
    Wrapped envelope { "data": [...], "meta": ... }.

    The data field is a list of invocation dicts, ordered by started_at
    descending. Each contains:
        - invocation_type: "slash_command" or "skill_tool"
        - first_request_id: cross-ref into the JSONL
        - session_id, session_file_path
        - started_at, duration_ms, n_requests
        - input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
        - total_tokens (sum convenience)
        - success: 0 or 1
        - cwd, model
        - trigger_line_offset, start_line_offset, end_line_offset:
          byte offsets into session_file_path. Use these with future
          JSONL drilldown tools to read the raw span content.

Example:
    skill_invocations(name="start-day", limit=10, days=14)
    # → 10 most recent start-day invocations in the last 14 days

Reads from: DB (no JSONL, no filesystem).
Side effects: none (read-only).
"""


@app.tool(description=_DESCRIPTION)
def skill_invocations(name: str, limit: int = 50, days: Optional[int] = None) -> dict:
    """Raw list of individual invocations of one skill.

    Args:
        name: skill name
        limit: max rows, newest first
        days: optional window in days
    """
    with db.connect(get_db_path()) as conn:
        rows = queries.skill_invocations(conn, name, limit=limit, days=days)
    return wrap(
        rows,
        tool="skill_invocations",
        params={"name": name, "limit": limit, "days": days},
        window=format_window(days),
    )
