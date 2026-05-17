from __future__ import annotations

from ... import queries
from ..base import Section, WindowedCommand
from ..format import fmt_avg_int, fmt_int


class Models(WindowedCommand):
    name = "models"
    help = "per-model token rollup"

    def run(self, args, conn) -> list[Section]:
        rows = queries.by_model(conn, days=args.days)
        return [Section(
            "Per-model rollup", rows, kind="table",
            columns=[
                ("model",           "model",  None,        "left",  "cyan"),
                ("calls",           "calls",  fmt_int,     "right", None),
                ("distinct_skills", "skills", fmt_int,     "right", None),
                ("total_tokens",    "tokens", fmt_int,     "right", "yellow"),
                ("avg_tokens",      "avg",    fmt_avg_int, "right", None),
            ],
        )]
