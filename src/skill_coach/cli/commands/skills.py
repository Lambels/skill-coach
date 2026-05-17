from __future__ import annotations

from ... import pricing, queries
from ..base import Section, WindowedCommand
from ..format import fmt_avg_int, fmt_cost, fmt_duration_ms, fmt_int


_BY_CHOICES = ["tokens", "cost", "calls", "duration", "hit_ratio", "output", "requests"]
_TYPE_CHOICES = ["slash", "tool"]
_TYPE_MAP = {"slash": "slash_command", "tool": "skill_tool"}


def _sort_key(by: str):
    if by == "tokens":     return lambda r: -(r.get("total_tokens") or 0)
    if by == "cost":       return lambda r: -(r.get("cost_usd")     or 0)
    if by == "calls":      return lambda r: -(r.get("calls")        or 0)
    if by == "duration":   return lambda r: -(r.get("avg_duration_ms") or 0)
    if by == "output":     return lambda r: -(r.get("total_output") or 0)
    if by == "requests":   return lambda r: -(r.get("avg_requests") or 0)
    if by == "hit_ratio":  return lambda r:  (r.get("cache_hit_ratio") or 0)  # ascending: worst first
    raise ValueError(f"unknown sort key: {by!r}")


def _hit_ratio_cell(r):
    if r is None:
        return ""
    v = float(r)
    if v < 0.5:
        return f"[red]{v:.3f}[/red]"
    if v < 0.8:
        return f"[yellow]{v:.3f}[/yellow]"
    return f"[green]{v:.3f}[/green]"


def _via_label(slash, tool) -> str:
    if slash and tool:
        return f"{slash}s/{tool}t"
    if slash:
        return f"{slash}s"
    if tool:
        return f"{tool}t"
    return ""


class Skills(WindowedCommand):
    name = "skills"
    aliases = ["sk"]
    help = "all skills, one row each, sortable + filterable"

    def register(self, parser):
        super().register(parser)
        parser.add_argument("--by", default="tokens", choices=_BY_CHOICES,
                            help="sort key (default: tokens)")
        parser.add_argument("--filter", dest="name_filter", default=None,
                            help="substring match on skill name")
        parser.add_argument("--min-calls", type=int, default=1,
                            help="hide skills with fewer than N invocations")
        parser.add_argument("--type", dest="invocation_type", default=None,
                            choices=_TYPE_CHOICES,
                            help="restrict to slash-invoked or tool-dispatched only")

    def run(self, args, conn) -> list[Section]:
        inv_type = _TYPE_MAP.get(args.invocation_type) if args.invocation_type else None
        rows = queries.all_skills_full(
            conn,
            days=args.days,
            min_calls=args.min_calls,
            name_filter=args.name_filter,
            invocation_type=inv_type,
        )

        cost_by_skill = {c["skill_name"]: c["cost_usd"] for c in pricing.cost_per_skill(conn, days=args.days)}
        for r in rows:
            r["cost_usd"] = cost_by_skill.get(r["skill_name"], 0.0)
            r["via"] = _via_label(r.get("slash_calls") or 0, r.get("tool_calls") or 0)

        rows.sort(key=_sort_key(args.by))

        window = f"last {args.days} days" if args.days else "all time"
        title = f"All skills ({window}, sorted by {args.by})"
        if args.name_filter:
            title += f" · filter={args.name_filter!r}"
        if args.invocation_type:
            title += f" · type={args.invocation_type}"

        return [Section(
            title, rows, kind="table",
            columns=[
                ("skill_name",      "skill",  None,             "left",  "cyan"),
                ("calls",           "n",      fmt_int,          "right", None),
                ("total_tokens",    "tokens", fmt_int,          "right", "yellow"),
                ("cost_usd",        "cost",   fmt_cost,         "right", "green"),
                ("cache_hit_ratio", "cache",  _hit_ratio_cell,  "right", None),
                ("avg_duration_ms", "dur",    fmt_duration_ms,  "right", "dim"),
                ("avg_requests",    "reqs",   lambda n: f"{n:.1f}" if n else "", "right", "dim"),
                ("via",             "via",    None,             "left",  "dim"),
            ],
        )]
