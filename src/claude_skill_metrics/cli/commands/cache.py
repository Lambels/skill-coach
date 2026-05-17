from __future__ import annotations

from ... import queries
from ..base import Section, WindowedCommand
from ..format import fmt_avg_int, fmt_int


def _hit_ratio_cell(r):
    if r is None:
        return ""
    v = float(r)
    if v < 0.5:
        return f"[red]{v:.3f}[/red]"
    if v < 0.8:
        return f"[yellow]{v:.3f}[/yellow]"
    return f"[green]{v:.3f}[/green]"


class Cache(WindowedCommand):
    name = "cache"
    help = "cache hit-ratio per skill (worst first)"

    def register(self, parser):
        super().register(parser)
        parser.add_argument("--min-calls", type=int, default=5)

    def run(self, args, conn) -> list[Section]:
        rows = queries.cache_health(conn, min_calls=args.min_calls, days=args.days)
        return [Section(
            "Cache health (worst first)", rows, kind="table",
            columns=[
                ("skill_name",         "skill",       None,            "left",  "cyan"),
                ("calls",              "calls",       fmt_int,         "right", None),
                ("cache_hit_ratio",    "hit_ratio",   _hit_ratio_cell, "right", None),
                ("avg_uncached_input", "avg_in",      fmt_avg_int,     "right", "dim"),
                ("avg_cache_read",     "avg_cache_r", fmt_avg_int,     "right", None),
                ("avg_cache_creation", "avg_cache_c", fmt_avg_int,     "right", None),
            ],
        )]
