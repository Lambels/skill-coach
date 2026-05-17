"""Root argparse and dispatch loop."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from .. import db
from ..indexer import DEFAULT_DB_PATH, DEFAULT_PROJECTS_DIR, index_sweep
from . import commands  # noqa: F401 — triggers auto-discovery
from .base import Command
from .render import print_sections_as_json, print_sweep_banner, render_sections, stderr


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skill-coach",
        description="Inspect token usage of Claude Code skills, from local session logs.",
    )
    p.add_argument("--db-path", default=DEFAULT_DB_PATH)
    p.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    p.add_argument("--no-sweep", action="store_true",
                   help="skip the index sweep before running the command")
    p.add_argument("--quiet", action="store_true",
                   help="suppress the sweep summary banner")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of tables")

    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    for name in sorted(Command.REGISTRY):
        cls = Command.REGISTRY[name]
        sp = sub.add_parser(name, help=cls.help, aliases=cls.aliases or [])
        instance = cls()
        instance.register(sp)
        sp.set_defaults(_command_cls=cls)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cls: type[Command] = args._command_cls
    instance = cls()

    if instance.needs_sweep and not args.no_sweep:
        r = index_sweep(args.db_path, args.projects_dir)
        print_sweep_banner(r, args.quiet)

    if instance.needs_sweep:
        with db.connect(args.db_path) as conn:
            sections = instance.run(args, conn)
    else:
        sections = instance.run(args, conn=None)

    if args.json:
        print_sections_as_json(sections)
    else:
        render_sections(sections)

    return 0


if __name__ == "__main__":
    sys.exit(main())
