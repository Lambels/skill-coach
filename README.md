# skill-coach

I use Claude Code daily but have no good way to see which of my skills is
quietly burning through tokens. skill-coach reads my session logs and
tells me. It also runs a `/coach` agent that proposes specific edits to
bring the cost down, without changing what the skill does.

Provisional. APIs, schema, and the tool surface are still moving. Local
only, no telemetry, no network.

## What it does

skill-coach indexes every `Skill` invocation across my Claude Code
sessions (`~/.claude/projects/**/*.jsonl`) into a SQLite file. From
there I can ask:

- which skills cost the most (tokens, USD, calls)
- how the cost spreads across sessions, projects, models, days
- the per-skill output, duration, and cache profile
- which calls are outliers and why
- whether yesterday's SKILL.md edit actually saved tokens

Three surfaces.

A **CLI** for quick read-only tables. The commands: `overview`, `top`,
`skill <name>`, `trend`, `sessions`, `project`, `cache`, `models`,
`reindex`. The index refreshes itself before each command.

An **MCP server** with 21 tools. Discovery, slicing, drilling, cache,
statistics, relations, comparison, content, maintenance. Full list in
the source (`src/skill_coach/mcp/tools/`).

A **`/coach` skill** the user invokes. It reads the MCP, scans for
known token-waste patterns, and proposes one or more edits to specific
SKILL.md files. Each suggestion ships with an argument for why it
doesn't change behavior, a predicted saving, and a verification step.
It never applies edits on its own and never touches functionality.

## How measurement works

Two invocation types. A slash command (the user types `/X`) and a
model-dispatched `tool_use(Skill, X)`. Both produce one meta line
where Claude Code inlines the skill's SKILL.md. A span starts at
that meta line and ends at the next meta line, the next fresh user
prompt, or EOF, whichever comes first. Tokens across the span are
summed, deduplicated by `request_id`.

The DB stores numbers and pointers only. Offsets back into the JSONLs.
Whenever a tool needs actual text (the SKILL.md the model saw, the
ARGUMENTS, the surrounding turns), it seeks straight to the recorded
offset. JSONL stays the source of truth.

## Install

```bash
git clone git@github.com:Lambels/skill-coach.git
cd skill-coach
pipx install -e .
```

Plug the MCP server into Claude Code:

```bash
claude mcp add -s user skill-coach skill-coach mcp serve
```

Install the `/coach` skill by symlinking the bundled directory:

```bash
ln -s "$(pwd)/skills/coach" ~/.claude/skills/coach
```

Restart Claude Code, then run `/coach`.

## Constraints

Python 3.12+. macOS or Linux. Reads `~/.claude/projects/**/*.jsonl`,
wherever Claude Code writes its sessions.

Stdlib only for the indexer, queries, and stats. The CLI uses `rich`.
The MCP server uses `fastmcp`.

Read-only on JSONLs. Read and write on its own SQLite file under
`~/.claude/`. No network, no telemetry, no daemon.

## License

MIT.
