"""Rich rendering: tables, panels, console singletons, section dispatch."""

from __future__ import annotations

import json
from typing import Iterable, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..indexer import SweepResult
from .base import ColumnSpec, Section


stdout = Console()
stderr = Console(stderr=True)


def render_table(
    title: Optional[str],
    rows: Iterable[dict],
    columns: list[ColumnSpec],
) -> Table:
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan", title_style="bold")
    for _, header, _, justify, style in columns:
        table.add_column(header, justify=justify, style=style or None, no_wrap=True)

    rows = list(rows)
    if not rows:
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


def render_panel(title: str, data) -> Panel:
    if isinstance(data, str):
        body = data
    elif isinstance(data, dict):
        body = "\n".join(f"[bold]{k}[/bold]: {v}" for k, v in data.items())
    else:
        body = str(data)
    return Panel(body, title=title or None, box=box.ROUNDED, padding=(0, 2))


_RENDERERS = {
    "table": lambda s: render_table(s.title, s.data, s.columns or _fallback_columns(s.data)),
    "panel": lambda s: render_panel(s.title, s.data),
}


def render_sections(sections: list[Section]) -> None:
    for s in sections:
        renderer = _RENDERERS.get(s.kind)
        if renderer is None:
            raise ValueError(f"unknown section kind: {s.kind!r}")
        stdout.print(renderer(s))


def print_sections_as_json(sections: list[Section]) -> None:
    payload = [{"title": s.title, "kind": s.kind, "data": s.data} for s in sections]
    print(json.dumps(payload, indent=2, default=str))


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
    stderr.print(f"[dim](sweep:[/dim] {' [dim]·[/dim] '.join(bits)} [dim]· {r.duration_ms}ms)[/dim]")
    for path, msg in r.errors[:5]:
        stderr.print(f"  [red]![/red] [dim]{path}[/dim]: {msg}")


def _fallback_columns(rows) -> list[ColumnSpec]:
    if not isinstance(rows, list) or not rows:
        return []
    return [(k, k, None, "left", None) for k in rows[0].keys()]
