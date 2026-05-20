"""reindex tool — refresh the index DB from current JSONLs on disk."""

from __future__ import annotations

from dataclasses import asdict

from ... import indexer
from .. import app, get_db_path
from ..result import wrap


_DESCRIPTION = """\
Run one full prune-then-ingest sweep over the JSONL directory.

The MCP server sweeps once on startup. Long-lived sessions then drift
out of sync: new Claude Code sessions create JSONLs the server hasn't
indexed, and the background cleanup deletes JSONLs leaving orphan rows
in the index. Call this tool to refresh.

Sweep semantics (same as the CLI):
    1. PRUNE — delete index rows whose source JSONL is gone from disk.
    2. INGEST — parse new files; reparse modified files; skip unchanged.

Idempotent and safe to call repeatedly. Typical cost is well under
100 ms when little has changed.

Questions this tool answers:
    - Has the underlying data drifted since the server started?
    - How many new sessions / invocations landed in the last hour?
    - Are stale orphan rows polluting my analysis?

Parameters:
    projects_dir (str, optional): override the default `~/.claude/projects`
        sweep root. Useful only for testing — leave unset in normal use.

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field mirrors `SweepResult`:
        - files_seen, files_skipped, files_indexed, files_pruned
        - rows_added: net new invocation rows
        - duration_ms
        - errors: list of (path, message) tuples; empty on a clean sweep.

Example:
    reindex()
    # → {"data": {"files_seen": 55, "files_pruned": 1, ...}}

Reads from: JSONL directory (rglob + per-file stat) + DB (writes).
Side effects: yes — modifies the index DB. Read-only for JSONLs.
"""


@app.tool(description=_DESCRIPTION)
def reindex(projects_dir: str = indexer.DEFAULT_PROJECTS_DIR) -> dict:
    """Refresh the index DB from disk. Idempotent."""
    result = indexer.index_sweep(get_db_path(), projects_dir)
    data = asdict(result)
    return wrap(
        data,
        tool="reindex",
        params={"projects_dir": projects_dir},
    )
