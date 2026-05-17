"""Sliding-window indexer: keeps the SQLite mirror in sync with on-disk JSONLs."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .parser import parse_session_file


DEFAULT_DB_PATH = "~/.claude/skill-metrics.db"
DEFAULT_PROJECTS_DIR = "~/.claude/projects"


@dataclass
class SweepResult:
    files_seen: int = 0
    files_skipped: int = 0
    files_indexed: int = 0
    files_pruned: int = 0
    rows_added: int = 0
    duration_ms: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def index_sweep(
    db_path: str | Path = DEFAULT_DB_PATH,
    projects_dir: str | Path = DEFAULT_PROJECTS_DIR,
) -> SweepResult:
    """One full prune-then-ingest sweep over the JSONL filesystem."""
    start_ns = time.monotonic_ns()
    result = SweepResult()

    db_path = Path(db_path).expanduser()
    projects_dir = Path(projects_dir).expanduser()

    db.init_db(db_path)

    if not projects_dir.exists():
        result.duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        return result

    current_paths = {str(p) for p in projects_dir.rglob("*.jsonl") if p.is_file()}
    result.files_seen = len(current_paths)

    with db.connect(db_path) as conn:
        # PHASE 1 — PRUNE: rows whose source JSONL is gone from disk
        known_paths = db.all_cursor_paths(conn)
        for path in known_paths - current_paths:
            try:
                db.prune_session(conn, path)
                result.files_pruned += 1
            except Exception as e:
                result.errors.append((path, f"prune: {type(e).__name__}: {e}"))

        # PHASE 2 — INGEST: parse new or changed files, skip the rest
        for path in current_paths:
            try:
                stat = os.stat(path)
            except FileNotFoundError:
                _prune_safe(conn, path, result, label="post-glob")
                continue

            cursor = db.get_cursor(conn, path)
            mtime_ms = int(stat.st_mtime * 1000)

            if cursor is not None and cursor["last_indexed_inode"] == stat.st_ino:
                unchanged = (
                    cursor["last_indexed_size"] == stat.st_size
                    and cursor["last_indexed_mtime"] == mtime_ms
                )
                if unchanged:
                    result.files_skipped += 1
                    continue

            try:
                records = list(parse_session_file(path))
                added = db.insert_invocations(conn, records)
                db.upsert_cursor(
                    conn,
                    path,
                    mtime=mtime_ms,
                    size=stat.st_size,
                    offset=stat.st_size,
                    inode=stat.st_ino,
                )
                result.files_indexed += 1
                result.rows_added += added
            except FileNotFoundError:
                _prune_safe(conn, path, result, label="mid-process")
            except Exception as e:
                result.errors.append((path, f"ingest: {type(e).__name__}: {e}"))

    result.duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
    return result


def _prune_safe(conn, path: str, result: SweepResult, label: str) -> None:
    try:
        db.prune_session(conn, path)
        result.files_pruned += 1
    except Exception as e:
        result.errors.append((path, f"{label} prune: {type(e).__name__}: {e}"))


def _smoke(db_path: str = "/tmp/csm-smoke.db", projects_dir: str = "~/.claude/projects") -> None:
    target = Path(db_path).expanduser()
    for ext in ("", "-wal", "-shm"):
        f = Path(str(target) + ext)
        if f.exists():
            f.unlink()

    print("--- sweep 1 (cold) ---")
    print(_fmt(index_sweep(db_path, projects_dir)))

    print("--- sweep 2 (warm — should skip everything) ---")
    print(_fmt(index_sweep(db_path, projects_dir)))

    print("--- DB summary ---")
    print(f"DB size      : {target.stat().st_size:,} bytes")
    with db.connect(db_path) as conn:
        n_inv = conn.execute("SELECT COUNT(*) FROM skill_invocations").fetchone()[0]
        n_cur = conn.execute("SELECT COUNT(*) FROM index_cursor").fetchone()[0]
        print(f"invocations  : {n_inv}")
        print(f"cursors      : {n_cur}")

        print("\ntop 10 skills by call count:")
        for row in conn.execute(
            "SELECT skill_name, COUNT(*) AS n, "
            "SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) AS tokens "
            "FROM skill_invocations GROUP BY skill_name ORDER BY n DESC LIMIT 10"
        ):
            print(f"  {row['n']:>4}  {row['skill_name']:<25}  tokens={row['tokens']:>10,}")


def _fmt(r: SweepResult) -> str:
    out = (
        f"files_seen    : {r.files_seen}\n"
        f"files_skipped : {r.files_skipped}\n"
        f"files_indexed : {r.files_indexed}\n"
        f"files_pruned  : {r.files_pruned}\n"
        f"rows_added    : {r.rows_added}\n"
        f"duration_ms   : {r.duration_ms}\n"
    )
    if r.errors:
        out += f"errors        : {len(r.errors)}\n"
        for path, msg in r.errors[:5]:
            out += f"  - {path}: {msg}\n"
    return out + "\n"


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) >= 2 else "/tmp/csm-smoke.db"
    _smoke(db_path)
