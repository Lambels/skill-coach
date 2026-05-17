from __future__ import annotations

from ... import queries
from ..base import Section, WindowedCommand
from ..format import fmt_duration_ms, fmt_int, fmt_short, fmt_success, fmt_ts


class Skill(WindowedCommand):
    name = "skill"
    help = "detailed stats for one skill"

    def register(self, parser):
        super().register(parser)
        parser.add_argument("skill_name")
        parser.add_argument("--limit", type=int, default=20)

    def run(self, args, conn) -> list[Section]:
        d = queries.skill_detail(conn, args.skill_name, days=args.days)
        if d is None:
            return [Section(
                "Not found",
                f"No data for skill [cyan]{args.skill_name}[/cyan] in window.",
                kind="panel",
            )]

        total_tokens = d["total_input"] + d["total_output"] + d["total_cache_read"] + d["total_cache_creation"]
        window = f"last {args.days} days" if args.days else "all time"

        header = "\n".join([
            f"[bold cyan]{d['skill_name']}[/bold cyan]",
            f"[dim]{window} · {fmt_ts(d['first_seen'])} → {fmt_ts(d['last_seen'])}[/dim]",
            "",
            f"[bold]Calls:[/bold]              {d['calls']:,}"
            f"   [dim]({d['slash_calls']} slash · {d['tool_calls']} tool)[/dim]",
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
            "[bold]Span shape[/bold]",
            f"  duration  avg = {fmt_duration_ms(d['avg_duration_ms'])}"
            f"   p50 = {fmt_duration_ms(d['p50_duration_ms'])}"
            f"   p95 = {fmt_duration_ms(d['p95_duration_ms'])}",
            f"  requests  avg = {d['avg_requests']:.1f}"
            f"   p50 = {d['p50_requests']:.0f}"
            f"   p95 = {d['p95_requests']:.0f}",
        ])

        invs = queries.skill_invocations(conn, args.skill_name, limit=args.limit, days=args.days)

        return [
            Section("Skill detail", header, kind="panel"),
            Section(
                "Recent invocations", invs, kind="table",
                columns=[
                    ("started_at",       "when",    fmt_ts,            "left",  None),
                    ("invocation_type",  "via",     None,              "left",  "dim"),
                    ("duration_ms",      "dur",     fmt_duration_ms,   "right", "dim"),
                    ("n_requests",       "reqs",    fmt_int,           "right", "dim"),
                    ("total_tokens",     "tokens",  fmt_int,           "right", "yellow"),
                    ("session_id",       "session", lambda s: fmt_short(s, 8), "left", "dim"),
                    ("success",          "ok",      fmt_success,       "center", None),
                ],
            ),
        ]
