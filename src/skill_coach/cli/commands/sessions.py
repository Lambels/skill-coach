from __future__ import annotations

from ... import queries
from ..base import Section, WindowedCommand
from ..format import fmt_int, fmt_path_tail, fmt_short, fmt_ts


class Sessions(WindowedCommand):
    name = "sessions"
    help = "most expensive sessions"

    def register(self, parser):
        super().register(parser)
        parser.add_argument("--limit", type=int, default=20)

    def run(self, args, conn) -> list[Section]:
        rows = queries.by_session(conn, limit=args.limit, days=args.days)
        return [Section(
            "Most expensive sessions", rows, kind="table",
            columns=[
                ("session_id",      "session", lambda s: fmt_short(s, 8), "left",  "dim"),
                ("started_at",      "when",    fmt_ts,             "left",  None),
                ("cwd",             "project", lambda s: fmt_path_tail(s, 30), "left", "dim"),
                ("calls",           "calls",   fmt_int,            "right", None),
                ("distinct_skills", "skills",  fmt_int,            "right", "cyan"),
                ("total_tokens",    "tokens",  fmt_int,            "right", "yellow"),
            ],
        )]
