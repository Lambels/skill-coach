"""MCP server lifecycle: optional initial sweep + stdio serve."""

from __future__ import annotations

import sys

from ..indexer import DEFAULT_DB_PATH, DEFAULT_PROJECTS_DIR, index_sweep
from . import app, set_db_path, tools  # noqa: F401 — `tools` triggers auto-discovery


def run(
    db_path: str = DEFAULT_DB_PATH,
    projects_dir: str = DEFAULT_PROJECTS_DIR,
    skip_sweep: bool = False,
) -> None:
    """Sweep the index once (unless skipped), then serve over stdio.

    stdio is the only transport for v1 — Claude Code plugs in directly.
    """
    set_db_path(db_path)

    if not skip_sweep:
        r = index_sweep(db_path, projects_dir)
        # Status banner goes to stderr so it doesn't pollute the stdio protocol channel.
        print(
            f"[skill-coach mcp] swept {r.files_indexed} new / {r.files_skipped} unchanged "
            f"({r.rows_added} rows, {r.duration_ms}ms)",
            file=sys.stderr,
        )
        if r.errors:
            print(f"[skill-coach mcp] {len(r.errors)} sweep errors", file=sys.stderr)

    app.run()
