"""Parse Claude Code session JSONL files into per-skill-invocation span records.

Two invocation types share one measurement algorithm:

  TYPE 1 — skill_tool   : model emits tool_use(Skill, X), then a banner
                          tool_result, then Claude Code injects the skill's
                          SKILL.md as a `isMeta=true` user line.
  TYPE 2 — slash_command: user types /X. The tag line is followed by Claude
                          Code's `isMeta=true` user line carrying the SKILL.md.

Both types' SPAN starts at the meta line and runs until the next trigger of
either kind OR the next fresh user prompt OR EOF. Tokens are summed across
all assistant requests in the span, dedup'd by request_id.

Records store only numbers + pointers; text content stays in the JSONL.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional


_SLASH_TAG_RE = re.compile(r"<command-name>/([^<\s]+)</command-name>")


@dataclass
class InvocationRecord:
    invocation_type: str            # 'skill_tool' | 'slash_command'

    # pointers / identity
    session_id: str
    session_file_path: str
    start_line_offset: int          # meta line (where SKILL.md begins)
    end_line_offset: Optional[int]  # last assistant line in span
    trigger_line_offset: int        # tool_use line OR slash tag line

    # context
    skill_name: str
    cwd: Optional[str]
    model: Optional[str]
    service_tier: Optional[str]

    # timing (epoch ms)
    started_at: int                 # meta line timestamp
    ended_at: int                   # last span line timestamp
    duration_ms: int

    # tokens (SUM across span, dedup'd by request_id)
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_5m_tokens: int
    cache_1h_tokens: int

    # span shape
    n_requests: int
    first_request_id: Optional[str]

    # outcome
    success: bool

def parse_session_file(path: str | Path) -> Iterator[InvocationRecord]:
    """Yield one InvocationRecord per completed skill-invocation span."""
    path = Path(path).expanduser()
    raw_lines = _read_lines_with_offsets(path)

    session_id = _first_value(raw_lines, "sessionId") or path.stem
    cwd = _first_value(raw_lines, "cwd")

    triggers = _find_triggers(raw_lines)
    invocations = _pair_with_meta(raw_lines, triggers)

    for inv in invocations:
        rec = _measure_span(raw_lines, inv, invocations, session_id, cwd, path)
        if rec is not None:
            yield rec

def _find_triggers(raw_lines: list[tuple[int, dict]]) -> list[dict]:
    """Locate every Skill tool_use AND every slash tag in order."""
    out: list[dict] = []
    for i, (offset, msg) in enumerate(raw_lines):
        mtype = msg.get("type")
        if mtype == "user":
            c = (msg.get("message") or {}).get("content")
            if isinstance(c, str):
                m = _SLASH_TAG_RE.search(c)
                if m:
                    out.append({
                        "idx": i, "offset": offset,
                        "type": "slash_command",
                        "skill_name": m.group(1),
                        "tool_use_id": None,
                        "timestamp": msg.get("timestamp"),
                    })
        elif mtype == "assistant":
            for b in (msg.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_use" and b.get("name") == "Skill":
                    inp = b.get("input") or {}
                    out.append({
                        "idx": i, "offset": offset,
                        "type": "skill_tool",
                        "skill_name": inp.get("skill", "") or "",
                        "tool_use_id": b.get("id"),
                        "timestamp": msg.get("timestamp"),
                    })
                    break  # one Skill per assistant message in observed data
    return out





def _pair_with_meta(
    raw_lines: list[tuple[int, dict]], triggers: list[dict]
) -> list[dict]:
    """For each trigger, find its isMeta=true user line. Triggers without a
    meta line are skipped (built-ins like /clear, or errored tool dispatches).
    Failed tool dispatches (with <tool_use_error>) yield a record with success=False
    and no measurable span."""
    invocations: list[dict] = []
    for t in triggers:
        meta_idx, meta_offset, meta_ts, errored = _find_meta_for(raw_lines, t)
        if meta_idx is not None:
            invocations.append({
                **t,
                "meta_idx": meta_idx,
                "meta_offset": meta_offset,
                "meta_ts": meta_ts,
                "failed": False,
            })
        elif errored:
            invocations.append({
                **t,
                "meta_idx": None,
                "meta_offset": None,
                "meta_ts": None,
                "failed": True,
            })
        # else: no meta and not errored → built-in slash like /clear, /compact — skip
    return invocations


def _find_meta_for(
    raw_lines: list[tuple[int, dict]], trigger: dict
) -> tuple[Optional[int], Optional[int], Optional[str], bool]:
    """Returns (meta_idx, meta_offset, meta_ts, errored). meta_* is None if no
    meta was found within reasonable distance. errored=True means we found a
    <tool_use_error> tool_result before the meta line (failed dispatch)."""
    for j in range(trigger["idx"] + 1, len(raw_lines)):
        joffset, jmsg = raw_lines[j]
        jtype = jmsg.get("type")

        # Skip lines that can appear between a trigger and its meta.
        if jtype in ("attachment", "file-history-snapshot", "system", "last-prompt"):
            continue

        if jtype != "user":
            # An assistant line before meta means the meta was never injected.
            return (None, None, None, False)

        jc = (jmsg.get("message") or {}).get("content")

        # For skill_tool, the tool_result line sits between the tool_use and the meta.
        if trigger["type"] == "skill_tool" and isinstance(jc, list):
            tool_result_block = next(
                (b for b in jc if isinstance(b, dict)
                 and b.get("type") == "tool_result"
                 and b.get("tool_use_id") == trigger["tool_use_id"]),
                None,
            )
            if tool_result_block is not None:
                content = tool_result_block.get("content") or ""
                if isinstance(content, str) and "<tool_use_error>" in content:
                    return (None, None, None, True)
                # OK tool_result — keep walking
                continue

        # The meta line: isMeta=true user line (content is a list of text blocks)
        if jmsg.get("isMeta") is True:
            return (j, joffset, jmsg.get("timestamp"), False)

        # Any other user line breaks the trigger→meta sequence
        return (None, None, None, False)

    return (None, None, None, False)

def _measure_span(
    raw_lines: list[tuple[int, dict]],
    inv: dict,
    all_invocations: list[dict],
    session_id: str,
    cwd: Optional[str],
    path: Path,
) -> Optional[InvocationRecord]:
    """Walk the span (meta_idx, span_end) and sum dedup'd token usage."""
    if inv["failed"]:
        ts_ms = _iso_to_ms(inv["timestamp"])
        return InvocationRecord(
            invocation_type=inv["type"],
            session_id=session_id,
            session_file_path=str(path),
            start_line_offset=inv["offset"],     # no meta — use trigger offset
            end_line_offset=None,
            trigger_line_offset=inv["offset"],
            skill_name=inv["skill_name"],
            cwd=cwd,
            model=None,
            service_tier=None,
            started_at=ts_ms,
            ended_at=ts_ms,
            duration_ms=0,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_5m_tokens=0,
            cache_1h_tokens=0,
            n_requests=0,
            first_request_id=None,
            success=False,
        )

    meta_idx = inv["meta_idx"]

    # Span ends at min(next meta after this one, next fresh user prompt, EOF).
    # Stopping at the next meta (not the next trigger) means the trigger line
    # itself is included in the outer skill's span — those tokens belong to the
    # skill whose SKILL.md is the most-recent meta above. Dedup by requestId
    # keeps multi-block responses from being double-counted.
    next_meta_idx = min(
        (o["meta_idx"] for o in all_invocations
         if o.get("meta_idx") is not None and o["meta_idx"] > meta_idx),
        default=len(raw_lines),
    )
    next_fresh_idx = len(raw_lines)
    for j in range(meta_idx + 1, len(raw_lines)):
        if _is_fresh_user_prompt(raw_lines[j][1]):
            next_fresh_idx = j
            break

    span_end_idx = min(next_meta_idx, next_fresh_idx)

    # In-flight at EOF (no boundary found) → orphan, skip.
    if span_end_idx == len(raw_lines):
        return None

    # Walk assistant lines in (meta_idx, span_end_idx); dedup by request_id.
    seen_reqs: set[str] = set()
    sum_in = sum_out = sum_cr = sum_cc = sum_5m = sum_1h = 0
    n_requests = 0
    first_req: Optional[str] = None
    model: Optional[str] = None
    service_tier: Optional[str] = None
    last_offset: Optional[int] = inv["meta_offset"]
    last_ts: Optional[str] = inv["meta_ts"]

    for j in range(meta_idx + 1, span_end_idx):
        joffset, jmsg = raw_lines[j]
        if jmsg.get("type") != "assistant":
            continue
        req = jmsg.get("requestId") or ""
        last_offset = joffset
        last_ts = jmsg.get("timestamp") or last_ts
        if not req or req in seen_reqs:
            continue
        seen_reqs.add(req)
        n_requests += 1
        if first_req is None:
            first_req = req
        message = jmsg.get("message") or {}
        if model is None:
            model = message.get("model")
        usage = message.get("usage") or {}
        if usage and service_tier is None:
            service_tier = usage.get("service_tier")
        sum_in += usage.get("input_tokens", 0) or 0
        sum_out += usage.get("output_tokens", 0) or 0
        sum_cr += usage.get("cache_read_input_tokens", 0) or 0
        sum_cc += usage.get("cache_creation_input_tokens", 0) or 0
        cc = usage.get("cache_creation") or {}
        sum_5m += cc.get("ephemeral_5m_input_tokens", 0) or 0
        sum_1h += cc.get("ephemeral_1h_input_tokens", 0) or 0

    started_at = _iso_to_ms(inv["meta_ts"])
    ended_at = _iso_to_ms(last_ts) if last_ts else started_at
    duration_ms = max(0, ended_at - started_at) if ended_at and started_at else 0

    return InvocationRecord(
        invocation_type=inv["type"],
        session_id=session_id,
        session_file_path=str(path),
        start_line_offset=inv["meta_offset"],
        end_line_offset=last_offset if n_requests > 0 else None,
        trigger_line_offset=inv["offset"],
        skill_name=inv["skill_name"],
        cwd=cwd,
        model=model,
        service_tier=service_tier,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        input_tokens=sum_in,
        output_tokens=sum_out,
        cache_read_tokens=sum_cr,
        cache_creation_tokens=sum_cc,
        cache_5m_tokens=sum_5m,
        cache_1h_tokens=sum_1h,
        n_requests=n_requests,
        first_request_id=first_req,
        success=True,
    )


def _is_fresh_user_prompt(msg: dict) -> bool:
    """A user-typed prompt that ENDS a span. Excludes:
       - meta lines (isMeta=true)
       - tool_result lines (list content with type=tool_result)
       - slash command tag lines (string content with <command-name>) — those
         are themselves triggers and ALREADY end the span via next-trigger logic.
    """
    if msg.get("type") != "user":
        return False
    if msg.get("isMeta") is True:
        return False
    c = (msg.get("message") or {}).get("content")
    if isinstance(c, str):
        return "<command-name>" not in c
    if isinstance(c, list):
        return not any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in c
        )
    return False

def _read_lines_with_offsets(path: Path) -> list[tuple[int, dict]]:
    out: list[tuple[int, dict]] = []
    with open(path, "rb") as f:
        offset = 0
        for raw in f:
            length = len(raw)
            try:
                msg = json.loads(raw)
                if isinstance(msg, dict):
                    out.append((offset, msg))
            except json.JSONDecodeError:
                pass
            offset += length
    return out


def _first_value(lines: list[tuple[int, dict]], key: str) -> Optional[str]:
    for _, msg in lines:
        v = msg.get(key)
        if v:
            return v
    return None


def _iso_to_ms(s: Optional[str]) -> int:
    if not s:
        return 0
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _smoke(path: str) -> None:
    import sys

    p = Path(path).expanduser()
    if not p.exists():
        print(f"file not found: {p}", file=sys.stderr)
        sys.exit(1)

    count = 0
    total_all = 0
    print(f"{'#':>3}  {'type':<14} {'skill':<22} {'reqs':>4} {'in':>5} {'out':>6}"
          f" {'cache_r':>9} {'cache_c':>7} {'TOTAL':>10}  {'dur':>7}  ok")
    print("─" * 110)
    for rec in parse_session_file(p):
        count += 1
        total = rec.input_tokens + rec.output_tokens + rec.cache_read_tokens + rec.cache_creation_tokens
        total_all += total
        dur = f"{rec.duration_ms}ms" if rec.duration_ms < 1000 else f"{rec.duration_ms/1000:.1f}s"
        print(
            f"{count:>3}  {rec.invocation_type:<14} {rec.skill_name:<22}"
            f" {rec.n_requests:>4} {rec.input_tokens:>5} {rec.output_tokens:>6}"
            f" {rec.cache_read_tokens:>9,} {rec.cache_creation_tokens:>7,}"
            f" {total:>10,}  {dur:>7}  {'✓' if rec.success else '✗'}"
        )
    print("─" * 110)
    print(f"{count} record(s)   total tokens: {total_all:,}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m claude_skill_metrics.parser <session.jsonl>", file=sys.stderr)
        sys.exit(2)
    _smoke(sys.argv[1])
