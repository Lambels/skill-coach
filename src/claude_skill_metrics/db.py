"""SQLite persistence for the skill metrics index."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable, Optional

from .parser import InvocationRecord


SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_invocations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id              TEXT NOT NULL,
    tool_use_id             TEXT NOT NULL,
    session_id              TEXT NOT NULL,
    session_file_path       TEXT NOT NULL,

    skill_name              TEXT NOT NULL,
    args_size_bytes         INTEGER,
    args_preview            TEXT,
    caller_type             TEXT,
    cwd                     TEXT,

    started_at              INTEGER NOT NULL,
    ended_at                INTEGER NOT NULL,
    duration_ms             INTEGER NOT NULL,

    model                   TEXT,
    service_tier            TEXT,

    input_tokens            INTEGER NOT NULL DEFAULT 0,
    output_tokens           INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_5m_tokens         INTEGER NOT NULL DEFAULT 0,
    cache_1h_tokens         INTEGER NOT NULL DEFAULT 0,
    thinking_tokens         INTEGER NOT NULL DEFAULT 0,

    result_size_bytes       INTEGER NOT NULL DEFAULT 0,
    iterations              INTEGER NOT NULL DEFAULT 1,
    web_searches            INTEGER NOT NULL DEFAULT 0,
    web_fetches             INTEGER NOT NULL DEFAULT 0,

    success                 INTEGER NOT NULL,
    error_message           TEXT,

    tool_use_line_offset    INTEGER,
    tool_result_line_offset INTEGER,

    UNIQUE(request_id, tool_use_id)
);

CREATE INDEX IF NOT EXISTS idx_skill   ON skill_invocations(skill_name);
CREATE INDEX IF NOT EXISTS idx_time    ON skill_invocations(started_at);
CREATE INDEX IF NOT EXISTS idx_session ON skill_invocations(session_id);
CREATE INDEX IF NOT EXISTS idx_cwd     ON skill_invocations(cwd);

CREATE TABLE IF NOT EXISTS index_cursor (
    session_file_path   TEXT PRIMARY KEY,
    last_indexed_mtime  INTEGER NOT NULL,
    last_indexed_size   INTEGER NOT NULL,
    last_indexed_offset INTEGER NOT NULL,
    last_indexed_inode  INTEGER NOT NULL,
    last_indexed_at     INTEGER NOT NULL
);
"""


INSERT_INVOCATION_SQL = """
INSERT OR IGNORE INTO skill_invocations (
    request_id, tool_use_id, session_id, session_file_path,
    skill_name, args_size_bytes, args_preview, caller_type, cwd,
    started_at, ended_at, duration_ms,
    model, service_tier,
    input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
    cache_5m_tokens, cache_1h_tokens, thinking_tokens,
    result_size_bytes, iterations, web_searches, web_fetches,
    success, error_message,
    tool_use_line_offset, tool_result_line_offset
) VALUES (
    ?, ?, ?, ?,
    ?, ?, ?, ?, ?,
    ?, ?, ?,
    ?, ?,
    ?, ?, ?, ?,
    ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?,
    ?, ?
)
"""


UPSERT_CURSOR_SQL = """
INSERT INTO index_cursor (
    session_file_path, last_indexed_mtime, last_indexed_size,
    last_indexed_offset, last_indexed_inode, last_indexed_at
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(session_file_path) DO UPDATE SET
    last_indexed_mtime  = excluded.last_indexed_mtime,
    last_indexed_size   = excluded.last_indexed_size,
    last_indexed_offset = excluded.last_indexed_offset,
    last_indexed_inode  = excluded.last_indexed_inode,
    last_indexed_at     = excluded.last_indexed_at
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with sane PRAGMAs and dict-like row access."""
    path = Path(path).expanduser()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | Path) -> None:
    """Create DB file and schema if missing. Idempotent."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def insert_invocations(conn: sqlite3.Connection, records: Iterable[InvocationRecord]) -> int:
    """Bulk insert. Returns number of rows actually added (after INSERT OR IGNORE)."""
    rows = [_record_to_tuple(r) for r in records]
    if not rows:
        return 0
    cur = conn.executemany(INSERT_INVOCATION_SQL, rows)
    return cur.rowcount


def get_cursor(conn: sqlite3.Connection, session_file_path: str) -> Optional[dict]:
    """Return cursor row as a dict, or None if no cursor for this path."""
    row = conn.execute(
        "SELECT * FROM index_cursor WHERE session_file_path = ?",
        (session_file_path,),
    ).fetchone()
    return dict(row) if row else None


def upsert_cursor(
    conn: sqlite3.Connection,
    session_file_path: str,
    mtime: int,
    size: int,
    offset: int,
    inode: int,
) -> None:
    """Insert or overwrite the cursor row for one JSONL file."""
    conn.execute(
        UPSERT_CURSOR_SQL,
        (session_file_path, mtime, size, offset, inode, int(time.time() * 1000)),
    )


def prune_session(conn: sqlite3.Connection, session_file_path: str) -> int:
    """Delete invocations + cursor for a vanished JSONL. Returns invocation rows deleted."""
    cur = conn.execute(
        "DELETE FROM skill_invocations WHERE session_file_path = ?",
        (session_file_path,),
    )
    deleted = cur.rowcount
    conn.execute(
        "DELETE FROM index_cursor WHERE session_file_path = ?",
        (session_file_path,),
    )
    return deleted


def all_cursor_paths(conn: sqlite3.Connection) -> set[str]:
    """Set of all JSONL paths we've ever indexed (and not since pruned)."""
    rows = conn.execute("SELECT session_file_path FROM index_cursor").fetchall()
    return {r["session_file_path"] for r in rows}


def _record_to_tuple(r: InvocationRecord) -> tuple:
    return (
        r.request_id, r.tool_use_id, r.session_id, r.session_file_path,
        r.skill_name, r.args_size_bytes, r.args_preview, r.caller_type, r.cwd,
        r.started_at, r.ended_at, r.duration_ms,
        r.model, r.service_tier,
        r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_creation_tokens,
        r.cache_5m_tokens, r.cache_1h_tokens, r.thinking_tokens,
        r.result_size_bytes, r.iterations, r.web_searches, r.web_fetches,
        int(r.success), r.error_message,
        r.tool_use_line_offset, r.tool_result_line_offset,
    )


def _smoke(jsonl_path: str, db_path: str = "/tmp/csm-smoke.db") -> None:
    from .parser import parse_session_file

    Path(db_path).unlink(missing_ok=True)
    init_db(db_path)
    records = list(parse_session_file(jsonl_path))
    print(f"parsed {len(records)} record(s) from {jsonl_path}")

    with connect(db_path) as conn:
        added = insert_invocations(conn, records)
        print(f"first insert : added {added} row(s)")
        added2 = insert_invocations(conn, records)
        print(f"second insert: added {added2} row(s)  (idempotency check; expect 0)")

        n = conn.execute("SELECT COUNT(*) FROM skill_invocations").fetchone()[0]
        print(f"row count    : {n}")

        print("\nGROUP BY skill_name:")
        for row in conn.execute(
            "SELECT skill_name, COUNT(*) AS n, "
            "SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) AS tokens "
            "FROM skill_invocations GROUP BY skill_name ORDER BY n DESC"
        ):
            print(f"  {row['n']:>3}  {row['skill_name']:<25}  tokens={row['tokens']:>8}")

        print("\ncursor round-trip:")
        upsert_cursor(conn, "/tmp/fake.jsonl", mtime=12345, size=678, offset=678, inode=999)
        cur = get_cursor(conn, "/tmp/fake.jsonl")
        print(f"  after upsert  : {cur}")
        upsert_cursor(conn, "/tmp/fake.jsonl", mtime=99999, size=10000, offset=10000, inode=999)
        cur = get_cursor(conn, "/tmp/fake.jsonl")
        print(f"  after update  : {cur}")

        print(f"  all paths     : {all_cursor_paths(conn)}")
        deleted = prune_session(conn, "/tmp/fake.jsonl")
        print(f"  pruned        : {deleted} invocation row(s)")
        print(f"  cursor after  : {get_cursor(conn, '/tmp/fake.jsonl')}")

        deleted = prune_session(conn, str(Path(jsonl_path).expanduser()))
        print(f"\npruning real session : deleted {deleted} invocation row(s)")
        n = conn.execute("SELECT COUNT(*) FROM skill_invocations").fetchone()[0]
        print(f"row count after prune: {n}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m claude_skill_metrics.db <session.jsonl> [db_path]", file=sys.stderr)
        sys.exit(2)
    db_path = sys.argv[2] if len(sys.argv) >= 3 else "/tmp/csm-smoke.db"
    _smoke(sys.argv[1], db_path)
