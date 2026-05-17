from __future__ import annotations

from ... import queries
from ..base import Section, WindowedCommand
from ..format import fmt_int


class Trend(WindowedCommand):
    name = "trend"
    help = "daily token-spend trend"

    def register(self, parser):
        super().register(parser)
        parser.add_argument("--skill", default=None)

    def run(self, args, conn) -> list[Section]:
        days = args.days if args.days is not None else 30
        rows = queries.daily_trend(conn, days=days, skill_name=args.skill)
        title = f"Daily trend ({days} days{', ' + args.skill if args.skill else ''})"
        return [Section(
            title, rows, kind="table",
            columns=[
                ("day",                   "day",      None,     "left",  None),
                ("calls",                 "calls",    fmt_int,  "right", None),
                ("input_tokens",          "input",    fmt_int,  "right", "dim"),
                ("output_tokens",         "output",   fmt_int,  "right", None),
                ("cache_read_tokens",     "cache_r",  fmt_int,  "right", "yellow"),
                ("cache_creation_tokens", "cache_c",  fmt_int,  "right", "yellow"),
            ],
        )]
