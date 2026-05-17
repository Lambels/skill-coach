"""MCP server package. Exposes a shared FastMCP app and the run entry point.

Tool modules live in `mcp/tools/`. Each module imports `app` from here and
registers tools via `@app.tool()`. Auto-discovered by `mcp/tools/__init__.py`.
"""

from __future__ import annotations

from fastmcp import FastMCP


app = FastMCP(name="skill-coach")


_db_path: str | None = None


def set_db_path(path: str) -> None:
    """Called by the CLI entry point before the server starts."""
    global _db_path
    _db_path = path


def get_db_path() -> str:
    if _db_path is None:
        from ..indexer import DEFAULT_DB_PATH
        return DEFAULT_DB_PATH
    return _db_path
