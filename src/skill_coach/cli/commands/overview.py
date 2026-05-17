from __future__ import annotations

from ... import pricing, queries
from ..base import Section, WindowedCommand
from ..format import fmt_avg_int, fmt_cost, fmt_duration_ms, fmt_int, fmt_ts


class Overview(WindowedCommand):
    name = "overview"
    aliases = ["o", "ov"]
    help = "totals + top skills + USD cost"

    def run(self, args, conn) -> list[Section]:
        ov = queries.overview(conn, days=args.days)
        if not ov.get("invocations"):
            return [Section("No data", "No invocations indexed yet.", kind="panel")]

        window = f"last {args.days} days" if args.days else "all time"
        header = "\n".join([
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
        ])

        top = queries.top_skills(conn, by="tokens", limit=10, days=args.days)
        cost = pricing.cost_per_skill(conn, days=args.days)[:10]

        return [
            Section("Headline", header, kind="panel"),
            Section(
                "Top skills by total tokens", top, kind="table",
                columns=[
                    ("skill_name",      "skill",  None,             "left",  "cyan"),
                    ("calls",           "calls",  fmt_int,          "right", None),
                    ("total_tokens",    "tokens", fmt_int,          "right", "yellow"),
                    ("avg_tokens",      "avg",    fmt_avg_int,      "right", None),
                    ("avg_duration_ms", "ms",     fmt_duration_ms,  "right", "dim"),
                ],
            ),
            Section(
                "Top skills by USD cost", cost, kind="table",
                columns=[
                    ("skill_name", "skill", None,    "left",  "cyan"),
                    ("calls",      "calls", fmt_int, "right", None),
                    ("cost_usd",   "cost",  fmt_cost,"right", "green"),
                ],
            ),
        ]
