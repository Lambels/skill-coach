# MCP tool surface

21 tools exposed by the skill-coach MCP server. Use them grouped by job.

## Discover — what's expensive

- `overview(days?)` — headline counts, totals, date range
- `top_skills(by, limit, days, min_calls, name_filter, invocation_type)`
  — ranked per-skill aggregate; sort by `tokens`, `cost`, `calls`,
  `avg_tokens`, `duration`, `output`, `requests`, `hit_ratio`
- `top_invocations(by, limit, days)` — single-call outliers (no
  aggregation)
- `cost_per_skill(days)` — USD breakdown per skill

## Slice — by axis

- `by_session(limit, days)` — most expensive sessions
- `by_project(days)` — per-(cwd, skill) breakdown
- `by_model(days)` — per-model rollup
- `daily_trend(days, skill?)` — time-series, optional single-skill filter

## Drill one skill

- `skill_detail(name, days)` — full aggregate + p50/p95 duration
- `skill_invocations(name, limit?, days?)` — raw row list (limit=None
  for all rows)

## Cache

- `cache_health(min_calls, days)` — per-skill hit ratio, worst first

## Statistical

- `get_distribution(skill, metric, days)` — mean, stddev, p25..p99 for
  one numeric metric. Metrics: `input_tokens`, `output_tokens`,
  `cache_read_tokens`, `cache_creation_tokens`, `total_tokens`,
  `duration_ms`, `n_requests`, `args_size_bytes`
- `find_outliers(skill, metric, threshold, days)` — invocations more
  than `threshold` stddev from the mean, with signed z-score
- `analyze_volatility(skill, days)` — coefficient of variation per
  metric for one skill

## Relate

- `find_skill_correlations(skill, window, days)` — preceded_by and
  followed_by frequency tables
- `get_session_skills(session_id)` — every skill invocation in one
  session, oldest first
- `get_skill_chain(session_file_path, start_line_offset)` — the full
  chain triggered by one user prompt, with the target's index marked

## Compare

- `compare_token_usage(a_path, a_off, b_path, b_off)` — side-by-side
  numerical delta; includes `skill_md_comparison` (same SKILL.md?) and
  `args_comparison` (raw ARGUMENTS text from both sides) so you can
  judge whether the comparison is apples-to-apples
- `compare_skill_md_versions(a_path, a_off, b_path, b_off)` — unified
  diff of the SKILL.md text both invocations actually ran. Short-
  circuits when the two `skill_md_hash` values match.

## Content

- `get_skill_md_at_invocation(path, off)` — the SKILL.md text as the
  model saw it for one specific invocation

## Maintain

- `reindex(projects_dir?)` — refresh the index from disk. Call this on
  long-lived sessions; the server only sweeps once on startup, so the
  index drifts over time. Idempotent and cheap.
