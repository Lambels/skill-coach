# Token-Reduction Heuristics

Catalog of patterns the coach scans for. Reference file — loaded by `SKILL.md`.
Each heuristic uses the same shape:

- **Signal** — measurable condition that triggers the heuristic
- **Detect with** — which MCP tools surface the signal
- **Diagnose** — what the signal usually means
- **Safe edit** — proposed change that preserves behavior
- **Why behavior-preserving** — explicit argument for safety
- **Verify after applying** — how to confirm the edit landed and saved tokens
- **Minimum n** — sample size below which estimates are LOW confidence
- **Default predicted savings** — starting heuristic-specific estimate;
  calibrate against real before/after data over time

Behavior-preservation is non-negotiable. If a heuristic cannot honestly carry
a **Why behavior-preserving** line, it does not belong here.

---

## Category A — Description bloat

The description sits in the model's system prompt EVERY session whether the
skill is invoked or not. Bytes here cost the most per byte.

### H1 — Verbose description on a rarely-used skill

- **Signal**: `invocations(30d) < 3` AND `description_tokens > 50`
- **Detect with**: `top_skills(by="calls", days=30)` to find rare skills;
  `get_skill_md_at_invocation` or read SKILL.md directly for description text
- **Diagnose**: descriptions over ~50 tokens almost always include
  example-shaped prose that belongs in the body, not the front matter. The
  description's job is one sentence: "when to use this".
- **Safe edit**: rewrite description as a single ≤30-token imperative
  sentence. Move any examples or context to the body.
- **Why behavior-preserving**: descriptions don't change what runs; they
  only change when the model picks the skill. A tighter description with
  the same trigger conditions selects identically.
- **Verify after applying**: `find_skill_correlations(skill)` before/after.
  If the "preceded_by" distribution stays similar, selection behavior
  didn't drift.
- **Minimum n**: 3 invocations to score; flag LOW until 5.
- **Default predicted savings**: ~`description_token_delta` per session
  (session-wide, not per-call).

### H1b — Description duplicates body opening

- **Signal**: first sentence of description equals first sentence of body
- **Detect with**: `get_skill_md_at_invocation` then string compare
- **Safe edit**: remove the redundant first body sentence.
- **Why behavior-preserving**: model sees both in context; deduping has no
  effect on dispatch.
- **Default predicted savings**: 10–30 tokens per call.

---

## Category B — Body bloat (hot skill)

Body loads into context on every invocation. For frequently-called skills
this dominates the bill.

### H2 — Bloated body, hot skill

- **Signal**: `invocations(30d) > 10` AND `body_tokens > 1500`
- **Detect with**: `top_skills(by="calls")` for the hot list;
  `get_skill_md_size` for body byte count
- **Diagnose**: bodies over ~1500 tokens almost always carry reference
  material that doesn't need to be in the primary load — examples,
  taxonomies, glossaries, error catalogs, code-style guides.
- **Safe edit**: move stable reference content to
  `skills/<name>/references/<topic>.md` and add a one-line pointer in
  SKILL.md (e.g. "see `references/error-codes.md` when handling errors").
  Claude Code lazy-loads referenced files only when the skill actually
  needs them.
- **Why behavior-preserving**: the same instructions remain reachable;
  they just don't preload. Behavior changes only if the model fails to
  follow the pointer — extremely rare for well-named reference files.
- **Verify after applying**: `compare_token_usage` on first post-edit
  invocation vs last pre-edit. Confirm `cache_creation` shrank.
- **Minimum n**: 5 invocations on each side; HIGH at 10+.
- **Default predicted savings**: 30–50% of `body_token_delta` per call.

### H2b — Conditional branches with branch-scoped templates

- **Signal**: body contains ≥ 3 distinct conditional blocks (markdown
  headers, `**Pattern X** → ...` markers, or "If A: ... else if B: ..."
  structures), each carrying its own template or rule set. AND
  `body_tokens > 1500`. AND not all branches typically fire on a given
  call.
- **Detect with**: `get_skill_md_at_invocation` then regex for branch
  markers; sample a few invocations via `get_skill_chain` or
  `skill_invocations` to confirm only a subset of branches actually
  fires on a typical run.
- **Diagnose**: every call pays the full body cost regardless of which
  branches fire. The unused branch templates are dead weight on the
  calls that don't hit them. Especially common on orchestrator skills
  (daily briefings, dispatchers) that handle multiple finding types
  with per-type formats.
- **Safe edit**: extract each branch's content to a topic-specific
  reference file (e.g. `references/template-A.md`,
  `references/template-B.md`). Replace each inline block in SKILL.md
  with a one-line pointer that names when to follow it ("When handling
  a new X, see `references/template-A.md` for the format.").
- **Why behavior-preserving**: same templates are reachable to the
  model — Claude Code lazy-loads referenced files when the body points
  at them. As long as the trigger language is descriptive enough for
  the model to recognise the case, the content arrives identically,
  just lazily.
- **Verify after applying**: `compare_token_usage` on calls known to
  fire different branch counts. The cache_creation drop should be
  largest on calls that hit only 1 branch.
- **Minimum n**: 5 invocations; HIGH at 10+ with at least 3 invocations
  per branch sampled.
- **Default predicted savings**: 30–50% of the extracted-branch tokens
  on calls that take a subset of branches; near 0% on calls that fire
  every branch.
- **Risk**: if the pointer language is weak ("see references/X.md"
  without context), the model may skip following it and emit a worse
  output shape for that branch. Mitigation: the pointer must name the
  condition AND the file (e.g. "When the finding is a contest, follow
  `references/template-contest.md` exactly.").

### H6 — Re-reads a large file every call

- **Signal**: SKILL.md body contains `Read(<path>)` or `cat <path>` where
  the referenced file is > 2 KB
- **Detect with**: `get_skill_md_at_invocation` then regex
- **Diagnose**: the skill repeatedly fetches the same large reference
  payload. If the content is stable across calls, it should live in the
  body (compact) or be referenced once per session (cached).
- **Safe edit**: inline the relevant section, or — if context-dependent —
  extract the actually-needed lines into a smaller helper file.
- **Why behavior-preserving**: same content available to the model, just
  delivered without round-tripping a tool call.
- **Default predicted savings**: ~size of the re-read file per call.

---

## Category C — Body waste (cold skill)

### H7 — Long body, low invocation count

- **Signal**: `body_tokens > 3000` AND `invocations(30d) < 5`
- **Detect with**: `get_skill_md_size` + `skill_detail(days=30)`
- **Diagnose**: large skill almost no one uses. Most likely abandoned
  scaffolding, but possibly a seasonal skill (end-of-quarter, audit-time)
  that genuinely has low frequency.
- **Safe edit**: do NOT delete. Produce a **review prompt** for the user.
- **Why behavior-preserving**: this heuristic only surfaces; no autonomous
  edit. Functionality stays untouched until user decides.
- **Verify after applying**: N/A (no automatic edit).

---

## Category D — Output bloat

The skill's output becomes the model's input on the NEXT turn. Output
tokens get billed twice in effect: once as completion, once as input on
the next call. Cutting output is high-leverage.

### H3 — Large average output

- **Signal**: `mean(output_tokens) > 1000` over the last 30 days
- **Detect with**: `get_distribution(skill, "output_tokens", days=30)` or
  `top_skills(by="output")`
- **Diagnose**: output format is unbounded; skill emits prose where a list
  or table would do, or repeats context the user already has.
- **Safe edit**: add explicit output discipline to SKILL.md:
  - "Respond with at most N lines."
  - "Use a fenced block, not prose."
  - "Do not restate the input."
  - "End with one sentence of next steps; nothing else."
- **Why behavior-preserving**: shape changes, semantics don't. The same
  information is conveyed in fewer tokens.
- **Verify after applying**: `compare_token_usage` last-pre-edit vs
  first-post-edit, focus on `output_tokens` delta.
- **Minimum n**: 5 calls on each side; t-test once `n_new ≥ 10`.
- **Default predicted savings**: 25–40% of output tokens.

### H4 — High output variance

- **Signal**: `stddev(output_tokens) > mean(output_tokens)` over 30 days
- **Detect with**: `analyze_volatility(skill)`
- **Diagnose**: output length is unconstrained; some calls are short, some
  are sprawling. The skill never tells the model where to stop.
- **Safe edit**: same kind of edit as H3 — add an explicit length bound
  the model can enforce.
- **Why behavior-preserving**: the long-output calls were doing extra work
  the skill never asked for. Cutting that excess matches the skill's
  intent rather than violating it.
- **Default predicted savings**: brings p95 toward the median; usually
  20–40% drop in average output.

### H8 — Output exceeds practical context

- **Signal**: `p95(output_tokens) > 4000`
- **Detect with**: `get_distribution(skill, "output_tokens")`
- **Diagnose**: tail-heavy output. A handful of calls produce so much that
  later turns have to drop earlier conversation to fit the model's window.
- **Safe edit**: introduce pagination ("return at most 20 rows, with a
  marker if more available") OR return-by-reference (write the full output
  to a file, return only the path + a summary).
- **Why behavior-preserving**: same data, accessible via one extra step.
  Only worth applying when the use case tolerates "go read this file".
- **Default predicted savings**: 50–80% on the tail; smaller on the mean.

---

## Category E — Boilerplate

### H5 — Output preamble / sign-off boilerplate

- **Signal**: SKILL.md body instructs the model to say something fixed
  every time. Patterns: `say "Done!"`, `start with "Sure,"`, `begin with
  a one-sentence summary`, `prefix with the skill name`.
- **Detect with**: `get_skill_md_at_invocation` then phrase scan
- **Diagnose**: these instructions add tokens to EVERY output and almost
  never serve the user — they exist as authoring habit.
- **Safe edit**: strip the instruction.
- **Why behavior-preserving**: the skill still does the work; it just
  doesn't narrate its participation.
- **Default predicted savings**: 10–30 tokens per call. Small per-call;
  large in aggregate on hot skills.

### H5b — Repeated reasoning preface

- **Signal**: body contains "First, think about X. Then think about Y.
  Then think about Z" where the three steps are not visibly used.
- **Diagnose**: ritual structure inherited from another skill. Often
  removable.
- **Safe edit**: leave structure when the model genuinely needs the
  scaffold. When unsure, do not propose; defer to user.
- **Why behavior-preserving**: if steps are decorative, removing them is
  free; if they ARE load-bearing, removal is a behavior change — so bias
  toward leaving them and asking the user.

---

## Category F — Hash and version signals

### F1 — Many SKILL.md hashes but unchanged behavior

- **Signal**: `COUNT(DISTINCT skill_md_hash) / COUNT(*) > 0.5` over 30
  days
- **Detect with**: per-skill SQL, or augmented `top_skills`
- **Diagnose**: two possibilities — (a) user is iterating heavily (real
  edits), or (b) SKILL.md contains dynamic content like shell
  substitutions (`` !`<cmd>` ``) Claude Code evaluates at load time.
  (b) is a false signal — same SKILL.md template, different rendered
  text per call.
- **How to disambiguate**: pick two invocations with different hashes,
  call `compare_skill_md_versions(a, b)`. If the only diff is one or two
  dynamic-looking lines (today's date, hostname, current time), it's (b)
  — discount the version churn for cost analysis.
- **Safe edit**: none — this heuristic is **interpretive**, not
  prescriptive. It tells the coach to discount apparent version churn,
  not to edit the skill.

### F2 — Real edits with no cost reduction

- **Signal**: multiple distinct SKILL.md hashes over 30d, AND no
  statistically significant change in `output_tokens` or `total_tokens`
  per call across hash transitions
- **Detect with**: `get_distribution` before and after each hash
  transition; Welch's t-test (n ≥ 10 per cohort).
- **Diagnose**: user is editing but the edits aren't reducing cost.
  Either edits are functional (not coach territory) or they target the
  wrong axis.
- **Safe edit**: produce a report — "N edits this month; observed cost
  change Z%. Consider examining heuristics A, C, D before the next
  round."

---

## Category G — Selection / chain hygiene

### G1 — Skill called only as part of one chain

- **Signal**: `n_occurrences` of skill almost always preceded by the
  same parent skill (e.g. `preceded_by[parent].pct > 0.9`)
- **Detect with**: `find_skill_correlations(skill, window=1)`
- **Diagnose**: the "skill" functions as a step of the parent skill.
  Keeping it standalone pays the per-invocation SKILL.md load on every
  parent run.
- **Safe edit**: do NOT auto-merge. Surface the suggestion: "skill X is
  preceded by skill Y in 92% of cases. Consider whether X should be
  inlined into Y's body, or kept separate for reuse elsewhere."
- **Why behavior-preserving**: merging is the user's call. Coach flags
  the pattern, no autonomous edit.

### G2 — Skill always followed by the same skill

- **Signal**: symmetric of G1, `followed_by[child].pct > 0.9`
- **Detect with**: `find_skill_correlations(skill, window=1)`
- **Diagnose / edit**: same flow as G1.

---

## Category H — Args drift

### H_args1 — Args size growing over time

- **Signal**: mean `args_size_bytes` in the last 7 days is > 2× the mean
  over the prior 30 days
- **Detect with**: `daily_trend(days=30, skill=X)` and
  `get_distribution(skill, "args_size_bytes")`
- **Diagnose**: scope creep — callers are stuffing more into args than
  the skill was designed for. Either the skill should declare its arg
  shape more tightly, or the calling sites are misusing it.
- **Safe edit**: add a "Required inputs" section to SKILL.md that
  explicitly bounds what args may contain.
- **Why behavior-preserving**: documenting the contract doesn't change
  it. It steers callers and the model toward tighter args.
- **Default predicted savings**: 20–50% of args size once tightened.

### H_args2 — Args dominate token cost

- **Signal**: `mean(args_size_bytes) > body_tokens × 4` (rough bytes/
  tokens parity)
- **Detect with**: `analyze_volatility` + `get_skill_md_size`
- **Diagnose**: the skill is essentially a thin wrapper around the
  payload the user passes in. No body-side edit will help.
- **Safe edit**: no edit — produce a report. "Skill X spends most of its
  input on args. Look at how args are formed at call sites, not at the
  skill itself."
- **Why behavior-preserving**: no edit proposed.

---

## Adding a heuristic

Keep entries to the same 8-field shape. Most importantly, every new
heuristic must have a **Why behavior-preserving** line. If that line
cannot be written honestly, the heuristic does not belong here — it
belongs in a separate functionality-change document the user reviews
manually.
