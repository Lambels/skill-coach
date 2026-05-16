"""CLI entry point — `claude-skill-stats <subcommand>`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import db, pricing, queries
from .indexer import DEFAULT_DB_PATH, DEFAULT_PROJECTS_DIR, SweepResult, index_sweep


_stdout = Console()
_stderr = Console(stderr=True)


# ────────────────────────────── value formatters ──────────────────────────────


def fmt_int(n) -> str:
    return f"{int(n):,}" if n is not None else ""


def fmt_int_or_blank(n) -> str:
    if n is None:
        return ""
    n = int(n)
    return f"{n:,}" if n else ""


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
    if n < 1024**2:
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
    return f"{float(r):.3f}" if r is not None else ""


def fmt_short(s, n: int = 8) -> str:
    return s[:n] if s else ""


def fmt_path_tail(s, n: int = 30) -> str:
    if not s:
        return ""
    return s if len(s) <= n else "…" + s[-(n - 1):]


def fmt_success(b) -> str:
    if b is None:
        return ""
    return "[green]✓[/green]" if b else "[red]✗[/red]"


# ────────────────────────────── table builder ──────────────────────────────


def render_table(
    title: Optional[str],
    rows: Iterable[dict],
    columns: list[tuple],
) -> Table:
    """columns: (key, header, formatter_or_None, justify, style)."""
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan", title_style="bold")
    for _, header, _, justify, style in columns:
        table.add_column(header, justify=justify, style=style or None, no_wrap=True)

    rows = list(rows)
    if not rows:
        # rich shows empty table cleanly; nothing to do
        return table

    for r in rows:
        cells = []
        for key, _, fmt, _, _ in columns:
            v = r.get(key)
            if fmt is not None:
                cells.append(fmt(v))
            elif v is None:
                cells.append("")
            else:
                cells.append(str(v))
        table.add_row(*cells)
    return table


# ────────────────────────────── sweep banner ──────────────────────────────


def print_sweep_banner(r: SweepResult, quiet: bool) -> None:
    if quiet:
        return
    if r.files_indexed == 0 and r.files_pruned == 0 and not r.errors:
        return
    bits = []
    if r.files_indexed:
        bits.append(f"[cyan]indexed[/cyan] {r.files_indexed}")
    if r.files_pruned:
        bits.append(f"[yellow]pruned[/yellow] {r.files_pruned}")
    if r.rows_added:
        bits.append(f"[green]+{r.rows_added} rows[/green]")
    if r.errors:
        bits.append(f"[red]{len(r.errors)} errors[/red]")
    _stderr.print(f"[dim](sweep:[/dim] {' [dim]·[/dim] '.join(bits)} [dim]· {r.duration_ms}ms)[/dim]")
    for path, msg in r.errors[:5]:
        _stderr.print(f"  [red]![/red] [dim]{path}[/dim]: {msg}")


# ────────────────────────────── command handlers ──────────────────────────────


def cmd_overview(args, conn) -> None:
    ov = queries.overview(conn, days=args.days)
    if not ov.get("invocations"):
        _stdout.print("[yellow]No invocations indexed yet.[/yellow]")
        return

    if args.json:
        print(json.dumps(ov, indent=2, default=str))
        return

    window = f"last {args.days} days" if args.days else "all time"

    header_lines = [
        f"[bold]Window:[/bold]      {window}",
        f"             [dim]{fmt_ts(ov['first_seen'])} → {fmt_ts(ov['last_seen'])}[/dim]",
        f"[bold]Invocations:[/bold] {ov['invocations']:,}",
        f"[bold]Skills:[/bold]      {ov['distinct_skills']}",
        f"[bold]Sessions:[/bold]    {ov['distinct_sessions']}",
        f"[bold]Projects:[/bold]    {ov['distinct_projects']}",
        "",
        "[bold]Tokens[/bold]",
        f"  input              [yellow]{ov['input_tokens']:>14,}[/yellow]",
        f"  output             [yellow]{ov['output_tokens']:>14,}[/yellow]",
        f"  cache_read         [yellow]{ov['cache_read_tokens']:>14,}[/yellow]",
        f"  cache_creation     [yellow]{ov['cache_creation_tokens']:>14,}[/yellow]",
    ]
    _stdout.print(Panel("\n".join(header_lines), box=box.ROUNDED, padding=(0, 2)))

    top = queries.top_skills(conn, by="tokens", limit=10, days=args.days)
    _stdout.print(render_table(
        "Top skills by total tokens",
        top,
        [
            ("skill_name",      "skill",  None,             "left",  "cyan"),
            ("calls",           "calls",  fmt_int,          "right", None),
            ("total_tokens",    "tokens", fmt_int,          "right", "yellow"),
            ("avg_tokens",      "avg",    lambda n: fmt_int(int(n)) if n else "", "right", None),
            ("avg_duration_ms", "ms",     lambda n: fmt_duration_ms(n) if n else "", "right", "dim"),
        ],
    ))

    cost_rows = _cost_per_skill(conn, days=args.days)[:10]
    _stdout.print(render_table(
        "Top skills by USD cost",
        cost_rows,
        [
            ("skill_name", "skill", None,    "left",  "cyan"),
            ("calls",      "calls", fmt_int, "right", None),
            ("cost_usd",   "cost",  fmt_cost,"right", "green"),
        ],
    ))


def cmd_skill(args, conn) -> None:
    d = queries.skill_detail(conn, args.name, days=args.days)
    if d is None:
        _stderr.print(f"[red]No data for skill[/red] [cyan]{args.name}[/cyan] [red]in window.[/red]")
        sys.exit(1)

    if args.json:
        print(json.dumps(d, indent=2, default=str))
        return

    total_tokens = d["total_input"] + d["total_output"] + d["total_cache_read"] + d["total_cache_creation"]

    header = [
        f"[bold cyan]{d['skill_name']}[/bold cyan]",
        f"[dim]{'last ' + str(args.days) + ' days' if args.days else 'all time'} · {fmt_ts(d['first_seen'])} → {fmt_ts(d['last_seen'])}[/dim]",
        "",
        f"[bold]Calls:[/bold]              {d['calls']:,}",
        f"[bold]Success rate:[/bold]       {d['success_rate']:.1%}",
        f"[bold]Distinct sessions:[/bold]  {d['distinct_sessions']}",
        f"[bold]Distinct projects:[/bold]  {d['distinct_projects']}",
        "",
        "[bold]Tokens[/bold]",
        f"  input              [yellow]{d['total_input']:>14,}[/yellow]",
        f"  output             [yellow]{d['total_output']:>14,}[/yellow]",
        f"  cache_read         [yellow]{d['total_cache_read']:>14,}[/yellow]",
        f"  cache_creation     [yellow]{d['total_cache_creation']:>14,}[/yellow]",
        f"  [bold]total[/bold]              [bold yellow]{total_tokens:>14,}[/bold yellow]",
        "",
        "[bold]Latency / shape[/bold]",
        f"  duration  avg = {fmt_duration_ms(d['avg_duration_ms'])}"
        f"   p50 = {fmt_duration_ms(d['p50_duration_ms'])}"
        f"   p95 = {fmt_duration_ms(d['p95_duration_ms'])}",
        f"  result    avg = {fmt_bytes(d['avg_result_bytes'])}"
        f"   p50 = {fmt_bytes(d['p50_result_bytes'])}"
        f"   p95 = {fmt_bytes(d['p95_result_bytes'])}",
    ]
    _stdout.print(Panel("\n".join(header), box=box.ROUNDED, padding=(0, 2)))

    invs = queries.skill_invocations(conn, args.name, limit=args.limit, days=args.days)
    _stdout.print(render_table(
        "Recent invocations",
        invs,
        [
            ("started_at",        "when",    fmt_ts,            "left",  None),
            ("duration_ms",       "dur",     fmt_duration_ms,   "right", "dim"),
            ("total_tokens",      "tokens",  fmt_int,           "right", "yellow"),
            ("result_size_bytes", "result",  fmt_bytes,         "right", None),
            ("session_id",        "session", lambda s: fmt_short(s, 8), "left", "dim"),
            ("success",           "ok",      fmt_success,       "center", None),
        ],
    ))


def cmd_trend(args, conn) -> None:
    rows = queries.daily_trend(conn, days=args.days, skill_name=args.skill)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    title = f"Daily trend ({args.days} days{', ' + args.skill if args.skill else ''})"
    _stdout.print(render_table(
        title,
        rows,
        [
            ("day",                   "day",      None,     "left",  None),
            ("calls",                 "calls",    fmt_int,  "right", None),
            ("input_tokens",          "input",    fmt_int,  "right", "dim"),
            ("output_tokens",         "output",   fmt_int,  "right", None),
            ("cache_read_tokens",     "cache_r",  fmt_int,  "right", "yellow"),
            ("cache_creation_tokens", "cache_c",  fmt_int,  "right", "yellow"),
        ],
    ))


def cmd_sessions(args, conn) -> None:
    rows = queries.by_session(conn, limit=args.limit, days=args.days)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    _stdout.print(render_table(
        "Most expensive sessions",
        rows,
        [
            ("session_id",      "session", lambda s: fmt_short(s, 8), "left",  "dim"),
            ("started_at",      "when",    fmt_ts,            "left",  None),
            ("cwd",             "project", lambda s: fmt_path_tail(s, 30), "left", "dim"),
            ("calls",           "calls",   fmt_int,           "right", None),
            ("distinct_skills", "skills",  fmt_int,           "right", "cyan"),
            ("total_tokens",    "tokens",  fmt_int,           "right", "yellow"),
        ],
    ))


def cmd_project(args, conn) -> None:
    rows = queries.by_project(conn, days=args.days)
    if args.cwd:
        rows = [r for r in rows if r.get("cwd") == args.cwd or (r.get("cwd") or "").endswith(args.cwd)]
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    _stdout.print(render_table(
        "Per-project breakdown",
        rows,
        [
            ("cwd",          "project", lambda s: fmt_path_tail(s, 35), "left",  "dim"),
            ("skill_name",   "skill",   None,    "left",  "cyan"),
            ("calls",        "calls",   fmt_int, "right", None),
            ("total_tokens", "tokens",  fmt_int, "right", "yellow"),
        ],
    ))


def cmd_top(args, conn) -> None:
    rows = queries.top_invocations(conn, by=args.by, limit=args.limit, days=args.days)
    for r in rows:
        r["cost_usd"] = pricing.cost_usd(r)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    # Show the column that matched the sort prominently, drop the others to keep table tight.
    extra_cols = {
        "tokens":      [],
        "duration":    [("duration_ms", "dur", fmt_duration_ms, "right", "dim")],
        "result_size": [("result_size_bytes", "result", fmt_bytes, "right", None)],
        "output":      [("output_tokens", "output", fmt_int, "right", None)],
    }[args.by]
    _stdout.print(render_table(
        f"Top {args.limit} invocations by {args.by}",
        rows,
        [
            ("skill_name",   "skill",   None,                       "left",   "cyan"),
            ("started_at",   "when",    fmt_ts,                     "left",   None),
            ("total_tokens", "tokens",  fmt_int,                    "right",  "yellow"),
            *extra_cols,
            ("cost_usd",     "cost",    fmt_cost,                   "right",  "green"),
            ("session_id",   "session", lambda s: fmt_short(s, 8),  "left",   "dim"),
        ],
    ))


def cmd_cache(args, conn) -> None:
    rows = queries.cache_health(conn, min_calls=args.min_calls, days=args.days)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return

    def hit_ratio_cell(r):
        if r is None:
            return ""
        v = float(r)
        if v < 0.5:
            return f"[red]{v:.3f}[/red]"
        if v < 0.8:
            return f"[yellow]{v:.3f}[/yellow]"
        return f"[green]{v:.3f}[/green]"

    _stdout.print(render_table(
        "Cache health (worst first)",
        rows,
        [
            ("skill_name",         "skill",       None,            "left",  "cyan"),
            ("calls",              "calls",       fmt_int,         "right", None),
            ("cache_hit_ratio",    "hit_ratio",   hit_ratio_cell,  "right", None),
            ("avg_uncached_input", "avg_in",      lambda n: fmt_int(int(n)) if n else "", "right", "dim"),
            ("avg_cache_read",     "avg_cache_r", lambda n: fmt_int(int(n)) if n else "", "right", None),
            ("avg_cache_creation", "avg_cache_c", lambda n: fmt_int(int(n)) if n else "", "right", None),
        ],
    ))


def cmd_models(args, conn) -> None:
    rows = queries.by_model(conn, days=args.days)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    _stdout.print(render_table(
        "Per-model rollup",
        rows,
        [
            ("model",           "model",   None,    "left",  "cyan"),
            ("calls",           "calls",   fmt_int, "right", None),
            ("distinct_skills", "skills",  fmt_int, "right", None),
            ("total_tokens",    "tokens",  fmt_int, "right", "yellow"),
            ("avg_tokens",      "avg",     lambda n: fmt_int(int(n)) if n else "", "right", None),
        ],
    ))


def cmd_reindex(args, conn=None) -> None:
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

    lines = [
        f"[bold]files_seen[/bold]    : {r.files_seen}",
        f"[bold]files_skipped[/bold] : {r.files_skipped}",
        f"[bold]files_indexed[/bold] : [cyan]{r.files_indexed}[/cyan]",
        f"[bold]files_pruned[/bold]  : [yellow]{r.files_pruned}[/yellow]",
        f"[bold]rows_added[/bold]    : [green]{r.rows_added}[/green]",
        f"[bold]duration_ms[/bold]   : {r.duration_ms}",
    ]
    if r.errors:
        lines.append(f"[bold]errors[/bold]        : [red]{len(r.errors)}[/red]")
        for path, msg in r.errors[:10]:
            lines.append(f"  [red]![/red] [dim]{path}[/dim]: {msg}")
    _stdout.print(Panel("\n".join(lines), title="Sweep result", box=box.ROUNDED, padding=(0, 2)))


# ────────────────────────────── helpers ──────────────────────────────


def _cost_per_skill(conn, days: Optional[int]) -> list[dict]:
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
    p.add_argument("--db-path", default=DEFAULT_DB_PATH)
    p.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    p.add_argument("--no-sweep", action="store_true",
                   help="skip the index sweep before running the command")
    p.add_argument("--quiet", action="store_true",
                   help="suppress the sweep summary banner")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of tables")

    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    s = sub.add_parser("overview", help="totals + top skills + USD cost")
    s.add_argument("--days", type=int, default=None)
    s.set_defaults(func=cmd_overview)

    s = sub.add_parser("skill", help="detailed stats for one skill")
    s.add_argument("name")
    s.add_argument("--days", type=int, default=None)
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_skill)

    s = sub.add_parser("trend", help="daily token-spend trend")
    s.add_argument("--days", type=int, default=30)
    s.add_argument("--skill", default=None)
    s.set_defaults(func=cmd_trend)

    s = sub.add_parser("sessions", help="most expensive sessions")
    s.add_argument("--days", type=int, default=None)
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_sessions)

    s = sub.add_parser("project", help="per-project breakdown")
    s.add_argument("cwd", nargs="?", default=None)
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

    if not args.no_sweep and args.command != "reindex":
        r = index_sweep(args.db_path, args.projects_dir)
        print_sweep_banner(r, args.quiet)

    if args.command == "reindex":
        cmd_reindex(args)
        return 0

    with db.connect(args.db_path) as conn:
        args.func(args, conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
