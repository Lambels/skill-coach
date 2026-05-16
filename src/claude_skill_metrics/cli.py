"""CLI entry point — `claude-skill-stats <subcommand>`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import db, pricing, queries
from .indexer import DEFAULT_DB_PATH, DEFAULT_PROJECTS_DIR, SweepResult, index_sweep


# ────────────────────────────── formatters ──────────────────────────────


def fmt_int(n) -> str:
    if n is None:
        return ""
    return f"{int(n):,}"


def fmt_float(n, places: int = 2) -> str:
    if n is None:
        return ""
    return f"{float(n):,.{places}f}"


def fmt_cost(c) -> str:
    if c is None:
        return ""
    c = float(c)
    if c == 0:
        return "$0"
    if c < 0.01:
        return f"${c:.4f}"
    return f"${c:.2f}"


def fmt_bytes(n) -> str:
    if n is None:
        return ""
    n = float(n)
    if n < 1024:
        return f"{int(n)}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}K"
    if n < 1024**3:
        return f"{n / 1024**2:.1f}M"
    return f"{n / 1024**3:.1f}G"


def fmt_duration_ms(n) -> str:
    if n is None:
        return ""
    n = float(n)
    if n < 1000:
        return f"{int(n)}ms"
    if n < 60_000:
        return f"{n / 1000:.1f}s"
    return f"{n / 60_000:.1f}m"


def fmt_ts(epoch_ms) -> str:
    if not epoch_ms:
        return ""
    dt = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def fmt_ratio(r) -> str:
    if r is None:
        return ""
    return f"{float(r):.3f}"


def fmt_short(s, n: int = 8) -> str:
    if not s:
        return ""
    return s[:n]


def fmt_path_tail(s, n: int = 30) -> str:
    if not s:
        return ""
    return s if len(s) <= n else "…" + s[-(n - 1):]


def fmt_table(rows: list[dict], columns: list[tuple]) -> str:
    """Render rows as a fixed-width table.

    columns: list of (key, header, formatter_or_None, alignment) tuples.
    alignment: 'l' for left, 'r' for right.
    """
    if not rows:
        return "  (no rows)\n"

    cell_rows: list[list[str]] = []
    for r in rows:
        cells = []
        for key, _, fmt, _ in columns:
            v = r.get(key)
            if fmt is not None:
                cells.append(fmt(v))
            elif v is None:
                cells.append("")
            else:
                cells.append(str(v))
        cell_rows.append(cells)

    headers = [c[1] for c in columns]
    aligns = [c[3] for c in columns]
    widths = [len(h) for h in headers]
    for cells in cell_rows:
        for i, c in enumerate(cells):
            if len(c) > widths[i]:
                widths[i] = len(c)

    def render(cells: list[str]) -> str:
        parts = []
        for i, c in enumerate(cells):
            if aligns[i] == "r":
                parts.append(f"{c:>{widths[i]}}")
            else:
                parts.append(f"{c:<{widths[i]}}")
        return "  ".join(parts)

    out = [render(headers), render(["─" * w for w in widths])]
    for cells in cell_rows:
        out.append(render(cells))
    return "\n".join(out) + "\n"


# ────────────────────────────── sweep banner ──────────────────────────────


def print_sweep_banner(r: SweepResult, quiet: bool) -> None:
    """Tell the user what the sweep did. Silent if nothing changed (or --quiet)."""
    if quiet:
        return
    if r.files_indexed == 0 and r.files_pruned == 0 and not r.errors:
        return
    bits = []
    if r.files_indexed:
        bits.append(f"indexed {r.files_indexed}")
    if r.files_pruned:
        bits.append(f"pruned {r.files_pruned}")
    if r.rows_added:
        bits.append(f"{r.rows_added} new rows")
    if r.errors:
        bits.append(f"{len(r.errors)} errors")
    print(f"(sweep: {', '.join(bits)} in {r.duration_ms}ms)", file=sys.stderr)
    for path, msg in r.errors[:5]:
        print(f"  ! {path}: {msg}", file=sys.stderr)


# ────────────────────────────── command handlers ──────────────────────────────


def cmd_overview(args, conn) -> None:
    ov = queries.overview(conn, days=args.days)
    if not ov.get("invocations"):
        print("No invocations indexed yet.")
        return

    if args.json:
        print(json.dumps(ov, indent=2, default=str))
        return

    window = f"last {args.days} days" if args.days else "all time"
    print(f"Window:      {window}")
    print(f"             {fmt_ts(ov['first_seen'])} → {fmt_ts(ov['last_seen'])}")
    print(f"Invocations: {ov['invocations']:,}")
    print(f"Skills:      {ov['distinct_skills']}")
    print(f"Sessions:    {ov['distinct_sessions']}")
    print(f"Projects:    {ov['distinct_projects']}")
    print()
    print("Tokens:")
    print(f"  input              {ov['input_tokens']:>14,}")
    print(f"  output             {ov['output_tokens']:>14,}")
    print(f"  cache_read         {ov['cache_read_tokens']:>14,}")
    print(f"  cache_creation     {ov['cache_creation_tokens']:>14,}")
    print()

    print("Top skills by total tokens:")
    top = queries.top_skills(conn, by="tokens", limit=10, days=args.days)
    print(fmt_table(
        top,
        [
            ("skill_name",      "skill",   None,                            "l"),
            ("calls",           "calls",   fmt_int,                         "r"),
            ("total_tokens",    "tokens",  fmt_int,                         "r"),
            ("avg_tokens",      "avg",     lambda n: fmt_int(int(n)) if n else "",  "r"),
            ("avg_duration_ms", "ms",      lambda n: fmt_duration_ms(n) if n else "",  "r"),
        ],
    ))

    # Spend ranking using pricing
    print("Top skills by USD cost:")
    cost_rows = _cost_per_skill(conn, days=args.days)
    print(fmt_table(
        cost_rows[:10],
        [
            ("skill_name", "skill", None,    "l"),
            ("calls",      "calls", fmt_int, "r"),
            ("cost_usd",   "cost",  fmt_cost,"r"),
        ],
    ))


def cmd_skill(args, conn) -> None:
    d = queries.skill_detail(conn, args.name, days=args.days)
    if d is None:
        print(f"No data for skill {args.name!r} in window.")
        sys.exit(1)

    if args.json:
        print(json.dumps(d, indent=2, default=str))
        return

    total_tokens = d["total_input"] + d["total_output"] + d["total_cache_read"] + d["total_cache_creation"]
    print(f"Skill:               {d['skill_name']}")
    print(f"Window:              {'last ' + str(args.days) + ' days' if args.days else 'all time'}")
    print(f"  {fmt_ts(d['first_seen'])} → {fmt_ts(d['last_seen'])}")
    print(f"Calls:               {d['calls']:,}")
    print(f"Success rate:        {d['success_rate']:.1%}")
    print(f"Distinct sessions:   {d['distinct_sessions']}")
    print(f"Distinct projects:   {d['distinct_projects']}")
    print()
    print("Tokens:")
    print(f"  input              {d['total_input']:>14,}")
    print(f"  output             {d['total_output']:>14,}")
    print(f"  cache_read         {d['total_cache_read']:>14,}")
    print(f"  cache_creation     {d['total_cache_creation']:>14,}")
    print(f"  total              {total_tokens:>14,}")
    print()
    print("Latency / shape:")
    print(f"  duration  avg = {fmt_duration_ms(d['avg_duration_ms'])}"
          f"   p50 = {fmt_duration_ms(d['p50_duration_ms'])}"
          f"   p95 = {fmt_duration_ms(d['p95_duration_ms'])}")
    print(f"  result    avg = {fmt_bytes(d['avg_result_bytes'])}"
          f"   p50 = {fmt_bytes(d['p50_result_bytes'])}"
          f"   p95 = {fmt_bytes(d['p95_result_bytes'])}")
    print()
    print("Recent invocations:")
    invs = queries.skill_invocations(conn, args.name, limit=args.limit, days=args.days)
    print(fmt_table(
        invs,
        [
            ("started_at",        "when",     fmt_ts,            "l"),
            ("duration_ms",       "dur",      fmt_duration_ms,   "r"),
            ("total_tokens",      "tokens",   fmt_int,           "r"),
            ("result_size_bytes", "result",   fmt_bytes,          "r"),
            ("session_id",        "session",  lambda s: fmt_short(s, 8),  "l"),
            ("success",           "ok",       lambda b: "✓" if b else "✗",  "l"),
        ],
    ))


def cmd_trend(args, conn) -> None:
    rows = queries.daily_trend(conn, days=args.days, skill_name=args.skill)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    print(fmt_table(
        rows,
        [
            ("day",                   "day",       None,    "l"),
            ("calls",                 "calls",     fmt_int, "r"),
            ("input_tokens",          "input",     fmt_int, "r"),
            ("output_tokens",         "output",    fmt_int, "r"),
            ("cache_read_tokens",     "cache_r",   fmt_int, "r"),
            ("cache_creation_tokens", "cache_c",   fmt_int, "r"),
        ],
    ))


def cmd_sessions(args, conn) -> None:
    rows = queries.by_session(conn, limit=args.limit, days=args.days)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    print(fmt_table(
        rows,
        [
            ("session_id",      "session",  lambda s: fmt_short(s, 8),  "l"),
            ("started_at",      "when",     fmt_ts,            "l"),
            ("cwd",             "project",  lambda s: fmt_path_tail(s, 30),  "l"),
            ("calls",           "calls",    fmt_int,           "r"),
            ("distinct_skills", "skills",   fmt_int,           "r"),
            ("total_tokens",    "tokens",   fmt_int,           "r"),
        ],
    ))


def cmd_project(args, conn) -> None:
    rows = queries.by_project(conn, days=args.days)
    if args.cwd:
        rows = [r for r in rows if r.get("cwd") == args.cwd or (r.get("cwd") or "").endswith(args.cwd)]
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    print(fmt_table(
        rows,
        [
            ("cwd",          "project",   lambda s: fmt_path_tail(s, 35),  "l"),
            ("skill_name",   "skill",     None,    "l"),
            ("calls",        "calls",     fmt_int, "r"),
            ("total_tokens", "tokens",    fmt_int, "r"),
        ],
    ))


def cmd_top(args, conn) -> None:
    rows = queries.top_invocations(conn, by=args.by, limit=args.limit, days=args.days)
    for r in rows:
        r["cost_usd"] = pricing.cost_usd(r)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    print(fmt_table(
        rows,
        [
            ("skill_name",        "skill",   None,             "l"),
            ("started_at",        "when",    fmt_ts,           "l"),
            ("total_tokens",      "tokens",  fmt_int,          "r"),
            ("output_tokens",     "out",     fmt_int,          "r"),
            ("duration_ms",       "dur",     fmt_duration_ms,  "r"),
            ("result_size_bytes", "result",  fmt_bytes,         "r"),
            ("cost_usd",          "cost",    fmt_cost,         "r"),
            ("session_id",        "session", lambda s: fmt_short(s, 8), "l"),
        ],
    ))


def cmd_cache(args, conn) -> None:
    rows = queries.cache_health(conn, min_calls=args.min_calls, days=args.days)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    print(fmt_table(
        rows,
        [
            ("skill_name",            "skill",       None,    "l"),
            ("calls",                 "calls",       fmt_int, "r"),
            ("cache_hit_ratio",       "hit_ratio",   fmt_ratio,"r"),
            ("avg_uncached_input",    "avg_in",      lambda n: fmt_int(int(n)) if n else "",  "r"),
            ("avg_cache_read",        "avg_cache_r", lambda n: fmt_int(int(n)) if n else "",  "r"),
            ("avg_cache_creation",    "avg_cache_c", lambda n: fmt_int(int(n)) if n else "",  "r"),
        ],
    ))


def cmd_models(args, conn) -> None:
    rows = queries.by_model(conn, days=args.days)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    print(fmt_table(
        rows,
        [
            ("model",           "model",   None,    "l"),
            ("calls",           "calls",   fmt_int, "r"),
            ("distinct_skills", "skills",  fmt_int, "r"),
            ("total_tokens",    "tokens",  fmt_int, "r"),
            ("avg_tokens",      "avg",     lambda n: fmt_int(int(n)) if n else "",  "r"),
        ],
    ))


def cmd_reindex(args, conn=None) -> None:
    # reindex doesn't use the connection; sweep manages its own.
    r = index_sweep(args.db_path, args.projects_dir)
    if args.json:
        out = {
            "files_seen": r.files_seen,
            "files_skipped": r.files_skipped,
            "files_indexed": r.files_indexed,
            "files_pruned": r.files_pruned,
            "rows_added": r.rows_added,
            "duration_ms": r.duration_ms,
            "errors": r.errors,
        }
        print(json.dumps(out, indent=2))
        return
    print(f"files_seen    : {r.files_seen}")
    print(f"files_skipped : {r.files_skipped}")
    print(f"files_indexed : {r.files_indexed}")
    print(f"files_pruned  : {r.files_pruned}")
    print(f"rows_added    : {r.rows_added}")
    print(f"duration_ms   : {r.duration_ms}")
    if r.errors:
        print(f"errors        : {len(r.errors)}")
        for path, msg in r.errors[:10]:
            print(f"  ! {path}: {msg}")


# ────────────────────────────── helpers ──────────────────────────────


def _cost_per_skill(conn, days: Optional[int]) -> list[dict]:
    """Aggregate USD cost per skill by walking individual rows.

    Required because pricing is model-dependent and the aggregate query
    SUMs across models — we need raw rows to apply the right rate.
    """
    tf_sql, tf_params = queries._time_filter(days)
    rows = conn.execute(
        f"""
        SELECT skill_name, model, input_tokens, output_tokens,
               cache_read_tokens, cache_5m_tokens, cache_1h_tokens
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        """,
        tf_params,
    ).fetchall()

    totals: dict[str, dict] = {}
    for row in rows:
        d = dict(row)
        skill = d["skill_name"]
        slot = totals.setdefault(skill, {"skill_name": skill, "calls": 0, "cost_usd": 0.0})
        slot["calls"] += 1
        slot["cost_usd"] += pricing.cost_usd(d)
    return sorted(totals.values(), key=lambda x: -x["cost_usd"])


# ────────────────────────────── argparse setup ──────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-skill-stats",
        description="Inspect token usage of Claude Code skills, from local session logs.",
    )
    p.add_argument("--db-path", default=DEFAULT_DB_PATH,
                   help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    p.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR,
                   help=f"Claude Code projects dir (default: {DEFAULT_PROJECTS_DIR})")
    p.add_argument("--no-sweep", action="store_true",
                   help="skip the index sweep before running the command")
    p.add_argument("--quiet", action="store_true",
                   help="suppress the sweep summary banner")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of tables")

    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    s = sub.add_parser("overview", help="totals + top skills + USD cost")
    s.add_argument("--days", type=int, default=None, help="window in days")
    s.set_defaults(func=cmd_overview)

    s = sub.add_parser("skill", help="detailed stats for one skill")
    s.add_argument("name", help="skill name (e.g. vault-find-related)")
    s.add_argument("--days", type=int, default=None)
    s.add_argument("--limit", type=int, default=20, help="recent invocations to show")
    s.set_defaults(func=cmd_skill)

    s = sub.add_parser("trend", help="daily token-spend trend")
    s.add_argument("--days", type=int, default=30)
    s.add_argument("--skill", default=None, help="filter to one skill")
    s.set_defaults(func=cmd_trend)

    s = sub.add_parser("sessions", help="most expensive sessions")
    s.add_argument("--days", type=int, default=None)
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_sessions)

    s = sub.add_parser("project", help="per-project breakdown")
    s.add_argument("cwd", nargs="?", default=None, help="optional cwd filter")
    s.add_argument("--days", type=int, default=None)
    s.set_defaults(func=cmd_project)

    s = sub.add_parser("top", help="top-N single invocations")
    s.add_argument("--by", default="tokens",
                   choices=["tokens", "duration", "result_size", "output"])
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--days", type=int, default=None)
    s.set_defaults(func=cmd_top)

    s = sub.add_parser("cache", help="cache hit-ratio per skill (worst first)")
    s.add_argument("--min-calls", type=int, default=5)
    s.add_argument("--days", type=int, default=None)
    s.set_defaults(func=cmd_cache)

    s = sub.add_parser("models", help="per-model token rollup")
    s.add_argument("--days", type=int, default=None)
    s.set_defaults(func=cmd_models)

    s = sub.add_parser("reindex", help="force a sweep and print the result")
    s.set_defaults(func=cmd_reindex)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Run the sweep first (lazy trigger). reindex re-runs it itself; suppress here.
    if not args.no_sweep and args.command != "reindex":
        r = index_sweep(args.db_path, args.projects_dir)
        print_sweep_banner(r, args.quiet)

    # reindex doesn't need a query connection
    if args.command == "reindex":
        cmd_reindex(args)
        return 0

    with db.connect(args.db_path) as conn:
        args.func(args, conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
