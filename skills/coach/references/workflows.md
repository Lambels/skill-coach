# Workflow recipes

Three opinionated workflows. Templates, not scripts — adapt when the data
points elsewhere.

## Recipe 1 — Triage (default `/coach` invocation)

When the user invokes `/coach` with no specific skill, find the worst
offender.

1. `reindex()` — make sure the index reflects current disk state.
2. `overview(days=30)` — frame the dataset for the user.
3. `top_skills(by="cost", limit=5, days=30, min_calls=5)` — rank by USD
   over the last 30 days, with a minimum-call filter to suppress noise.
4. For the top 1–3 skills:
   - `skill_detail(name, days=30)` — character profile.
   - `cache_health` for that skill (or read it off `top_skills` row).
   - Scan `references/heuristics.md` for matches (start with categories
     A, B, D — they cover most of the leverage).
5. Pick the heuristic with the highest `priority` per skill. Produce one
   ranked suggestion per targeted skill, capped at 3 total suggestions.
6. End with: which skills you flagged, which heuristics matched, what
   the user would do next.

## Recipe 2 — Explain anomaly

When the user asks "why was this invocation so expensive?" or points at
a single high-cost call.

1. Identify the invocation by `(session_file_path, start_line_offset)`.
   If the user only gave a session id or a date, narrow it via
   `get_session_skills` or `skill_invocations(name)`.
2. `find_outliers(skill, metric="total_tokens", threshold=2.0)` — is
   this row genuinely an outlier or just typical?
3. `get_skill_chain(path, off)` — what else ran under the same user
   prompt? Cost often comes from chain context, not the skill itself.
4. Pick a typical invocation of the same skill (from
   `skill_invocations`) and call `compare_token_usage(typical, outlier)`.
   Read the `delta` to find which metric drives the gap (output?
   cache_creation? args?).
5. Check `skill_md_comparison.same_md` and `args_comparison`. If the
   SKILL.md or args differ, the comparison is confounded — say so.
6. End with: the most plausible cause, ranked by evidence.

## Recipe 3 — Verify a recent edit

When the user says "I edited X yesterday; did it help?"

1. `skill_invocations(name=X, days=14)` — pull both pre- and post-edit
   calls in one shot.
2. Split the list at the boundary where `skill_md_hash` flips. Pick a
   representative pre-edit invocation and a representative post-edit
   one (similar args length, similar session depth).
3. `compare_skill_md_versions(pre, post)` — confirm the edit landed and
   inspect what changed.
4. `compare_token_usage(pre, post)` — read the deltas. Lead with
   `output_tokens` and `cache_creation_tokens`; those are the levers a
   SKILL.md edit moves.
5. Apply the confidence tier rules from `SKILL.md`. If post-edit n < 5,
   say LOW and stop. If 5–29, give a range. If ≥ 30, give a point
   estimate with 95% CI from `get_distribution` on both cohorts.
6. End with: observed savings, confidence tier, recommendation (keep
   the edit / revert / iterate).
