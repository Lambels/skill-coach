from __future__ import annotations

from ..base import Command, Section


class Mcp(Command):
    name = "mcp"
    help = "run the MCP server (stdio) so an agent can query the index"
    needs_sweep = False        # the server does its own initial sweep
    produces_tables = False    # no Rich output; this just blocks on stdio

    def register(self, parser):
        sub = parser.add_subparsers(dest="mcp_action", required=True, metavar="<action>")

        s = sub.add_parser("serve", help="serve over stdio for a connected Claude Code session")
        s.add_argument("--skip-sweep", action="store_true",
                       help="don't run an initial index sweep before serving")

    def run(self, args, conn) -> list[Section]:
        if args.mcp_action == "serve":
            from ...mcp.server import run
            run(
                db_path=args.db_path,
                projects_dir=args.projects_dir,
                skip_sweep=args.skip_sweep,
            )
        return []
