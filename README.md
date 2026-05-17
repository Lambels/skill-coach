# skill-coach

A local tool that indexes Claude Code session logs (`~/.claude/projects/**/*.jsonl`) into SQLite and lets you see, per Claude Code skill, how many tokens you're spending — broken down by input, output, cache reads, cache writes, model, project, and session. CLI + (later) local web dashboard. Stdlib-only, read-only against the JSONLs.
