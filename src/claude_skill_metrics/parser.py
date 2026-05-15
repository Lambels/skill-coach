"""Parse a Claude Code session JSONL file into per-Skill-invocation records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class InvocationRecord:
    # identity
    request_id: str
    tool_use_id: str
    session_id: str
    session_file_path: str

    # the call
    skill_name: str
    args_size_bytes: int
    args_preview: str
    caller_type: str
    cwd: Optional[str]

    # timing (epoch ms)
    started_at: int
    ended_at: int
    duration_ms: int

    # model
    model: Optional[str]
    service_tier: Optional[str]

    # tokens
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_5m_tokens: int
    cache_1h_tokens: int
    thinking_tokens: int

    # shape / side effects
    result_size_bytes: int
    iterations: int
    web_searches: int
    web_fetches: int

    # outcome
    success: bool
    error_message: Optional[str]

    # JSONL pointers
    tool_use_line_offset: int
    tool_result_line_offset: Optional[int]


def parse_session_file(path: str | Path) -> Iterator[InvocationRecord]:
    """Yield one InvocationRecord per completed Skill tool_use → tool_result pair.

    Skill invocations whose request_id contains any other tool_use (including
    another Skill) are *skipped entirely* — the Anthropic API reports usage
    at request granularity, so we cannot cleanly attribute tokens between the
    co-located tool_uses. Better to omit than to record an imprecise figure.
    """
    path = Path(path).expanduser()
    raw_lines = _read_lines_with_offsets(path)

    session_id = _first_value(raw_lines, "sessionId") or path.stem
    cwd = _first_value(raw_lines, "cwd")
    thinking_chars_by_req = _thinking_chars_by_request(raw_lines)
    usage_by_req = _usage_by_request(raw_lines)
    tool_count_by_req = _tool_use_counts_by_request(raw_lines)

    pending: dict[str, InvocationRecord] = {}

    for offset, msg in raw_lines:
        mtype = msg.get("type")

        if mtype == "assistant":
            message = msg.get("message", {}) or {}
            request_id = msg.get("requestId") or ""
            timestamp = msg.get("timestamp")
            content = message.get("content", []) or []

            if tool_count_by_req.get(request_id, 0) > 1:
                continue

            for block in content:
                if not (block.get("type") == "tool_use" and block.get("name") == "Skill"):
                    continue

                tuid = block.get("id") or ""
                inp = block.get("input", {}) or {}
                args_json = json.dumps(inp, ensure_ascii=False)
                usage, model = usage_by_req.get(request_id, ({}, None))
                cache_creation = usage.get("cache_creation", {}) or {}
                server_tool_use = usage.get("server_tool_use", {}) or {}

                rec = InvocationRecord(
                    request_id=request_id,
                    tool_use_id=tuid,
                    session_id=session_id,
                    session_file_path=str(path),
                    skill_name=inp.get("skill", "") or "",
                    args_size_bytes=len(args_json.encode("utf-8")),
                    args_preview=args_json[:200],
                    caller_type=(block.get("caller") or {}).get("type", "direct"),
                    cwd=cwd,
                    started_at=_iso_to_ms(timestamp),
                    ended_at=0,
                    duration_ms=0,
                    model=model,
                    service_tier=usage.get("service_tier"),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    cache_5m_tokens=cache_creation.get("ephemeral_5m_input_tokens", 0),
                    cache_1h_tokens=cache_creation.get("ephemeral_1h_input_tokens", 0),
                    thinking_tokens=thinking_chars_by_req.get(request_id, 0) // 4,
                    result_size_bytes=0,
                    iterations=max(1, len(usage.get("iterations", []) or [])),
                    web_searches=server_tool_use.get("web_search_requests", 0),
                    web_fetches=server_tool_use.get("web_fetch_requests", 0),
                    success=True,
                    error_message=None,
                    tool_use_line_offset=offset,
                    tool_result_line_offset=None,
                )
                pending[tuid] = rec

        elif mtype == "user":
            message = msg.get("message", {}) or {}
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") != "tool_result":
                    continue
                tuid = block.get("tool_use_id")
                if tuid not in pending:
                    continue
                rec = pending.pop(tuid)
                rec.result_size_bytes = _measure_result_size(block.get("content"))
                rec.tool_result_line_offset = offset
                rec.ended_at = _iso_to_ms(msg.get("timestamp"))
                if rec.ended_at and rec.started_at:
                    rec.duration_ms = max(0, rec.ended_at - rec.started_at)
                tur = msg.get("toolUseResult")
                if isinstance(tur, dict) and "success" in tur:
                    rec.success = bool(tur["success"])
                yield rec

    for rec in pending.values():
        rec.success = False
        rec.error_message = "orphan: no tool_result before end of file"
        yield rec


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


def _usage_by_request(lines: list[tuple[int, dict]]) -> dict[str, tuple[dict, Optional[str]]]:
    """First non-empty usage block per request_id, plus the model that produced it."""
    out: dict[str, tuple[dict, Optional[str]]] = {}
    for _, msg in lines:
        if msg.get("type") != "assistant":
            continue
        req = msg.get("requestId")
        if not req or req in out:
            continue
        message = msg.get("message") or {}
        usage = message.get("usage") or {}
        if usage:
            out[req] = (usage, message.get("model"))
    return out


def _tool_use_counts_by_request(lines: list[tuple[int, dict]]) -> dict[str, int]:
    """Count content-block tool_uses (any tool) per request_id."""
    out: dict[str, int] = {}
    for _, msg in lines:
        if msg.get("type") != "assistant":
            continue
        req = msg.get("requestId")
        if not req:
            continue
        for block in (msg.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                out[req] = out.get(req, 0) + 1
    return out


def _thinking_chars_by_request(lines: list[tuple[int, dict]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, msg in lines:
        if msg.get("type") != "assistant":
            continue
        req = msg.get("requestId")
        if not req:
            continue
        for block in (msg.get("message") or {}).get("content") or []:
            if block.get("type") == "thinking":
                text = block.get("thinking", "")
                if isinstance(text, str):
                    out[req] = out.get(req, 0) + len(text)
    return out


def _measure_result_size(content) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    if isinstance(content, list):
        total = 0
        for b in content:
            if isinstance(b, dict):
                t = b.get("text") or b.get("content") or ""
                if isinstance(t, str):
                    total += len(t.encode("utf-8"))
                else:
                    total += len(json.dumps(t, ensure_ascii=False).encode("utf-8"))
            elif isinstance(b, str):
                total += len(b.encode("utf-8"))
        return total
    return len(json.dumps(content, ensure_ascii=False).encode("utf-8"))


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
    for rec in parse_session_file(p):
        count += 1
        total = (
            rec.input_tokens
            + rec.output_tokens
            + rec.cache_read_tokens
            + rec.cache_creation_tokens
        )
        print(
            f"#{count:>3}  {rec.skill_name:<25}  "
            f"in={rec.input_tokens:>6}  out={rec.output_tokens:>5}  "
            f"cache_r={rec.cache_read_tokens:>6}  cache_c={rec.cache_creation_tokens:>5}  "
            f"total={total:>7}  result_b={rec.result_size_bytes:>6}  "
            f"dur_ms={rec.duration_ms:>5}  ok={rec.success}"
        )
    print(f"\n{count} record(s)")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m claude_skill_metrics.parser <session.jsonl>", file=sys.stderr)
        sys.exit(2)
    _smoke(sys.argv[1])
