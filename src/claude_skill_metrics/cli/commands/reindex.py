from __future__ import annotations

from ...indexer import index_sweep
from ..base import Command, Section


class Reindex(Command):
    name = "reindex"
    help = "force a full sweep and print the result"
    needs_sweep = False

    def register(self, parser):
        pass

    def run(self, args, conn) -> list[Section]:
        r = index_sweep(args.db_path, args.projects_dir)

        body_lines = [
            f"[bold]files_seen[/bold]    : {r.files_seen}",
            f"[bold]files_skipped[/bold] : {r.files_skipped}",
            f"[bold]files_indexed[/bold] : [cyan]{r.files_indexed}[/cyan]",
            f"[bold]files_pruned[/bold]  : [yellow]{r.files_pruned}[/yellow]",
            f"[bold]rows_added[/bold]    : [green]{r.rows_added}[/green]",
            f"[bold]duration_ms[/bold]   : {r.duration_ms}",
        ]
        if r.errors:
            body_lines.append(f"[bold]errors[/bold]        : [red]{len(r.errors)}[/red]")
            for path, msg in r.errors[:10]:
                body_lines.append(f"  [red]![/red] [dim]{path}[/dim]: {msg}")

        return [Section("Sweep result", "\n".join(body_lines), kind="panel")]
