from __future__ import annotations

from ... import pricing, queries
from ..base import Section, WindowedCommand
from ..format import fmt_cost, fmt_duration_ms, fmt_int, fmt_short, fmt_ts


_BY_CHOICES = ["tokens", "duration", "output", "requests"]


class Top(WindowedCommand):
    name = "top"
    help = "top-N single invocations"

    def register(self, parser):
        super().register(parser)
        parser.add_argument("--by", default="tokens", choices=_BY_CHOICES)
        parser.add_argument("--limit", type=int, default=20)

    def run(self, args, conn) -> list[Section]:
        rows = queries.top_invocations(conn, by=args.by, limit=args.limit, days=args.days)
        for r in rows:
            r["cost_usd"] = pricing.cost_usd(r)

        extra_cols = {
            "tokens":   [],
            "duration": [("duration_ms",  "dur",    fmt_duration_ms, "right", "dim")],
            "output":   [("output_tokens", "output", fmt_int,         "right", None)],
            "requests": [("n_requests",    "reqs",   fmt_int,         "right", None)],
        }[args.by]

        return [Section(
            f"Top {args.limit} invocations by {args.by}", rows, kind="table",
            columns=[
                ("skill_name",      "skill",   None,                       "left",  "cyan"),
                ("invocation_type", "via",     None,                       "left",  "dim"),
                ("started_at",      "when",    fmt_ts,                     "left",  None),
                ("total_tokens",    "tokens",  fmt_int,                    "right", "yellow"),
                *extra_cols,
                ("cost_usd",        "cost",    fmt_cost,                   "right", "green"),
                ("session_id",      "session", lambda s: fmt_short(s, 8),  "left",  "dim"),
            ],
        )]
