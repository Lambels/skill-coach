"""Pure string formatters. No Rich, no I/O."""

from __future__ import annotations

from datetime import datetime, timezone


def fmt_int(n) -> str:
    return f"{int(n):,}" if n is not None else ""


def fmt_int_or_blank(n) -> str:
    if n is None:
        return ""
    n = int(n)
    return f"{n:,}" if n else ""


def fmt_cost(c) -> str:
    if c is None:
        return ""
    c = float(c)
    if c == 0:
        return "$0"
    if c < 0.01:
        return f"${c:.4f}"
    return f"${c:.2f}"


def fmt_bytes(n) -> str:
    if n is None:
        return ""
    n = float(n)
    if n < 1024:
        return f"{int(n)}B"
    if n < 1024**2:
        return f"{n / 1024:.1f}K"
    if n < 1024**3:
        return f"{n / 1024**2:.1f}M"
    return f"{n / 1024**3:.1f}G"


def fmt_duration_ms(n) -> str:
    if n is None:
        return ""
    n = float(n)
    if n < 1000:
        return f"{int(n)}ms"
    if n < 60_000:
        return f"{n / 1000:.1f}s"
    return f"{n / 60_000:.1f}m"


def fmt_ts(epoch_ms) -> str:
    if not epoch_ms:
        return ""
    dt = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def fmt_ratio(r) -> str:
    return f"{float(r):.3f}" if r is not None else ""


def fmt_short(s, n: int = 8) -> str:
    return s[:n] if s else ""


def fmt_path_tail(s, n: int = 30) -> str:
    if not s:
        return ""
    return s if len(s) <= n else "…" + s[-(n - 1):]


def fmt_success(b) -> str:
    if b is None:
        return ""
    return "[green]✓[/green]" if b else "[red]✗[/red]"


def fmt_avg_int(n) -> str:
    return fmt_int(int(n)) if n else ""
