"""get_skill_chain — reconstruct the chain of skills triggered by one user prompt."""

from __future__ import annotations

from ... import db, queries
from .. import app, get_db_path, jsonl_seek
from ..result import wrap


_DESCRIPTION = """\
Reconstruct the full skill chain that the target invocation belongs to.

A "chain" is the contiguous run of skill invocations within a single
session that share one originating fresh user prompt. Boundaries are
detected by scanning the JSONL between consecutive invocations for a
fresh user prompt (`parser.is_fresh_user_prompt`): no fresh prompt
between rows ⇒ same chain.

Pure-DB cousin: `get_session_skills` returns every invocation in the
session in order. This tool slices that down to the one chain the target
sits in, which is usually what the coach actually wants.

Questions this tool answers:
    - What did the user kick off with that prompt?
    - Was this invocation a standalone call or part of a longer chain?
    - What ran before / after this one, under the same prompt?
    - Where does this skill sit in the chain (position N of M)?

Parameters:
    session_file_path (str), start_line_offset (int):
        Composite key of any invocation in the chain.

Returns:
    Wrapped envelope { "data": {...}, "meta": ... }.

    The data field is a dict:
        - target_index: 0-based position of the target row inside `chain`
        - chain: list of invocation dicts ordered by started_at ASC,
          one entry per skill invocation in this chain. Same shape as
          `session_invocations` rows (includes pointers).
        - n_skills: len(chain)
        - distinct_skills: count of unique skill_name values

    Empty chain and target_index = -1 when the target row cannot be
    located in the index.

Example:
    get_skill_chain(
        session_file_path="/Users/.../sess.jsonl",
        start_line_offset=900,
    )
    # → returns brain-dump → vault-find-related → vault-link → vault-moc-suggest

Reads from: DB (session_invocations) + JSONL (boundary scan between rows).
Side effects: none (read-only).
"""


def _chain_for_target(invocations: list[dict], target_idx: int) -> list[dict]:
    """Walk outwards from target_idx, splitting on intervening fresh prompts."""
    start = target_idx
    while start > 0:
        prev = invocations[start - 1]
        curr = invocations[start]
        # End offset is None for failed dispatches — fall back to trigger.
        after = prev.get("end_line_offset") or prev["trigger_line_offset"]
        before = curr["trigger_line_offset"]
        if jsonl_seek.has_fresh_prompt_between(curr["session_file_path"], after, before):
            break
        start -= 1

    end = target_idx
    while end < len(invocations) - 1:
        curr = invocations[end]
        nxt = invocations[end + 1]
        after = curr.get("end_line_offset") or curr["trigger_line_offset"]
        before = nxt["trigger_line_offset"]
        if jsonl_seek.has_fresh_prompt_between(curr["session_file_path"], after, before):
            break
        end += 1

    return invocations[start : end + 1]


@app.tool(description=_DESCRIPTION)
def get_skill_chain(
    session_file_path: str,
    start_line_offset: int,
) -> dict:
    """The full skill chain (same user prompt) that the target invocation belongs to."""
    with db.connect(get_db_path()) as conn:
        target = queries.invocation_by_pointer(conn, session_file_path, start_line_offset)
        if target is None:
            return wrap(
                {"target_index": -1, "chain": [], "n_skills": 0, "distinct_skills": 0},
                tool="get_skill_chain",
                params={"session_file_path": session_file_path,
                        "start_line_offset": start_line_offset},
            )
        all_invocs = queries.session_invocations(conn, target["session_id"])

    target_idx = next(
        (i for i, inv in enumerate(all_invocs)
         if inv["session_file_path"] == session_file_path
         and inv["start_line_offset"] == start_line_offset),
        -1,
    )
    if target_idx < 0:
        return wrap(
            {"target_index": -1, "chain": [], "n_skills": 0, "distinct_skills": 0},
            tool="get_skill_chain",
            params={"session_file_path": session_file_path,
                    "start_line_offset": start_line_offset},
        )

    chain = _chain_for_target(all_invocs, target_idx)
    new_target_idx = next(
        i for i, inv in enumerate(chain)
        if inv["session_file_path"] == session_file_path
        and inv["start_line_offset"] == start_line_offset
    )

    return wrap(
        {
            "target_index": new_target_idx,
            "chain": chain,
            "n_skills": len(chain),
            "distinct_skills": len({c["skill_name"] for c in chain}),
        },
        tool="get_skill_chain",
        params={"session_file_path": session_file_path,
                "start_line_offset": start_line_offset},
    )
