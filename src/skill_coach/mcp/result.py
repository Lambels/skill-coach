"""Result envelope for every MCP tool response.

Shape locked at v1:
    {"data": <payload>, "meta": {"tool": str, "params": dict, "window": str|None, "row_count": int}}

No `next` field — we deliberately ship without hypermedia hints for v1.
Revisit if agent testing shows the coach wasting turns on tool discovery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def wrap(
    data: Any,
    *,
    tool: str,
    params: Optional[dict] = None,
    window: Optional[str] = None,
) -> dict:
    """Envelope a tool's return value with provenance metadata."""
    if isinstance(data, list):
        row_count = len(data)
    elif data is None:
        row_count = 0
    elif isinstance(data, dict):
        row_count = 1
    else:
        row_count = 1

    return {
        "data": data,
        "meta": {
            "tool": tool,
            "params": params or {},
            "window": window,
            "row_count": row_count,
        },
    }


def format_window(days: Optional[int], first_seen_ms: Optional[int] = None,
                  last_seen_ms: Optional[int] = None) -> str:
    """Render a human-readable window string for the meta envelope."""
    if days is None:
        base = "all time"
    else:
        base = f"last {days} days"
    if first_seen_ms and last_seen_ms:
        a = datetime.fromtimestamp(first_seen_ms / 1000, tz=timezone.utc).date()
        b = datetime.fromtimestamp(last_seen_ms / 1000, tz=timezone.utc).date()
        return f"{base} ({a} → {b})"
    return base
