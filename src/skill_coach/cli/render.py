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


class ColumnFilterError(ValueError):
    """User passed an unknown column name to --cols/--add/--drop."""


def list_available_columns(sections: list[Section]) -> None:
    """Print the available columns per table section, marking defaults.

    Mirrors _filter_one_section's rule: if default_columns is None, every
    column is shown by default. Only when default_columns is an explicit
    list does the section have opt-in (non-default) columns.
    """
    any_printed = False
    for s in sections:
        if s.kind != "table" or not s.columns:
            continue
        any_printed = True
        defaults = set(s.default_columns) if s.default_columns is not None else None
        stdout.print(f"[bold]{s.title}[/bold]")
        for key, header, _, _, _ in s.columns:
            if defaults is None:
                in_default = True
            else:
                in_default = (header in defaults) or (key in defaults)
            marker = "[green]●[/green]" if in_default else "[dim]○[/dim]"
            stdout.print(f"  {marker} [cyan]{header}[/cyan]  [dim](key: {key})[/dim]")
        if defaults is not None:
            stdout.print(f"  [dim]● = shown by default, ○ = opt-in via --add[/dim]")
        else:
            stdout.print(f"  [dim]all columns shown by default; use --drop to hide some[/dim]")
    if not any_printed:
        stderr.print("[yellow]This command produces no table sections.[/yellow]")


def apply_column_filters(
    sections: list[Section],
    cols: Optional[str],
    add: Optional[str],
    drop: Optional[str],
) -> list[Section]:
    """Resolve each table section's visible columns.

    Without --cols/--add/--drop, the section's `default_columns` (if set)
    selects which of `columns` are shown; otherwise all `columns` show.
    Selection is matched against either column header OR its data key.
    Panel sections are passed through unchanged.
    """
    out = []
    for s in sections:
        if s.kind != "table" or not s.columns:
            out.append(s)
            continue
        out.append(_filter_one_section(s, cols, add, drop))
    return out


def _filter_one_section(
    s: Section,
    cols: Optional[str],
    add: Optional[str],
    drop: Optional[str],
) -> Section:
    all_cols = list(s.columns)
    by_header = {c[1]: c for c in all_cols}
    by_key = {c[0]: c for c in all_cols if c[0]}

    def resolve(name: str):
        if name in by_header:
            return by_header[name]
        if name in by_key:
            return by_key[name]
        choices = ", ".join(c[1] for c in all_cols)
        raise ColumnFilterError(
            f"unknown column {name!r} in section {s.title!r}. "
            f"available: {choices}"
        )

    def split(v: Optional[str]) -> list[str]:
        return [x.strip() for x in v.split(",") if x.strip()] if v else []

    if cols:
        chosen = [resolve(n) for n in split(cols)]
    else:
        # Start from section's declared default (if any), else show every column.
        if s.default_columns:
            chosen = [resolve(n) for n in s.default_columns]
        else:
            chosen = list(all_cols)
        for name in split(drop):
            target = resolve(name)
            chosen = [c for c in chosen if c is not target]
        for name in split(add):
            chosen.append(resolve(name))

    return Section(
        title=s.title, data=s.data, kind=s.kind,
        columns=chosen,
        default_columns=s.default_columns,
    )


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
