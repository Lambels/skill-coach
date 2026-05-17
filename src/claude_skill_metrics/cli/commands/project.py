from __future__ import annotations

from ... import queries
from ..base import Section, WindowedCommand
from ..format import fmt_int, fmt_path_tail


class Project(WindowedCommand):
    name = "project"
    help = "per-project breakdown"

    def register(self, parser):
        super().register(parser)
        parser.add_argument("cwd", nargs="?", default=None)

    def run(self, args, conn) -> list[Section]:
        rows = queries.by_project(conn, days=args.days)
        if args.cwd:
            rows = [r for r in rows if r.get("cwd") == args.cwd or (r.get("cwd") or "").endswith(args.cwd)]
        return [Section(
            "Per-project breakdown", rows, kind="table",
            columns=[
                ("cwd",          "project", lambda s: fmt_path_tail(s, 35), "left",  "dim"),
                ("skill_name",   "skill",   None,    "left",  "cyan"),
                ("calls",        "calls",   fmt_int, "right", None),
                ("total_tokens", "tokens",  fmt_int, "right", "yellow"),
            ],
        )]
