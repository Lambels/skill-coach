"""Targeted reads into Claude Code session JSONLs.

The DB stores only numbers + pointers (`session_file_path`, `start_line_offset`,
`end_line_offset`, `trigger_line_offset`). Whenever an MCP tool needs the
underlying content — SKILL.md text, the per-call ARGUMENTS, the raw
tool_use args, surrounding conversation — it seeks straight to the
recorded byte offset and parses one line.

Seek-by-offset means content access is single-digit ms regardless of
JSONL file size. No scanning, no caching, no daemon. Side-effect free.

Public surface used by MCP tools:
    read_meta_at(path, offset)      -> (md_text, args_text) | None
    read_skill_md_at(path, offset)  -> md_text | None
    read_args_at(path, offset)      -> args_text | None

The meta-line parsing (text-block concatenation + ARGUMENTS split) lives
in `skill_coach.parser` and is shared with the indexer so the two layers
never drift on what counts as a meta line.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .. import parser as _parser


def _read_line_at(session_file_path: str, offset: int) -> Optional[dict]:
    """Open the JSONL, seek to `offset`, read one line, parse JSON.

    Returns the parsed dict or None on any failure (missing file, bad
    offset, malformed JSON). Tools should treat None as "no content
    available" and surface it cleanly to the agent.
    """
    p = Path(session_file_path).expanduser()
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            f.seek(offset)
            raw = f.readline()
    except OSError:
        return None
    if not raw:
        return None
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return msg if isinstance(msg, dict) else None


def read_meta_at(
    session_file_path: str,
    start_line_offset: int,
) -> Optional[tuple[str, Optional[str]]]:
    """Read the meta line and return (skill_md_text, args_text).

    `args_text` is None when no `\\n\\nARGUMENTS:` block is appended
    (some skills accept no arguments). The outer return is None when
    the line cannot be read at all.
    """
    msg = _read_line_at(session_file_path, start_line_offset)
    if msg is None:
        return None
    if msg.get("isMeta") is not True:
        # The offset didn't land on a meta line. The indexer should never
        # produce this; surface as None so the caller can flag stale data.
        return None
    text = _parser.extract_meta_text(msg)
    md, args = _parser.split_md_and_args(text)
    return md, args


def read_skill_md_at(
    session_file_path: str,
    start_line_offset: int,
) -> Optional[str]:
    """Just the SKILL.md prefix from the meta line."""
    pair = read_meta_at(session_file_path, start_line_offset)
    return pair[0] if pair else None


def read_args_at(
    session_file_path: str,
    start_line_offset: int,
) -> Optional[str]:
    """Just the ARGUMENTS tail from the meta line. None when absent."""
    pair = read_meta_at(session_file_path, start_line_offset)
    return pair[1] if pair else None
