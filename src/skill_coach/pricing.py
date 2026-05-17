"""Model → token-pricing table + cost computation.

Prices are in USD per million tokens (Mtok), Anthropic's published rates.
Last updated: 2026-05-15. Verify against https://www.anthropic.com/pricing
when in doubt; rates change.

Cache TTL pricing follows Anthropic's standard multipliers on the input rate:
  - cache_read:     0.10× input
  - cache_5m write: 1.25× input
  - cache_1h write: 2.00× input
"""

from __future__ import annotations

from typing import Optional


_OPUS = {
    "input":      15.00,
    "output":     75.00,
    "cache_read":  1.50,
    "cache_5m":   18.75,
    "cache_1h":   30.00,
}

_SONNET = {
    "input":       3.00,
    "output":     15.00,
    "cache_read":  0.30,
    "cache_5m":    3.75,
    "cache_1h":    6.00,
}

_HAIKU = {
    "input":       1.00,
    "output":      5.00,
    "cache_read":  0.10,
    "cache_5m":    1.25,
    "cache_1h":    2.00,
}


MODEL_PRICING: dict[str, dict[str, float]] = {
    # Opus 4 family
    "claude-opus-4-7":          _OPUS,
    "claude-opus-4-6":          _OPUS,
    "claude-opus-4-5":          _OPUS,
    "claude-opus-4-1":          _OPUS,
    "claude-opus-4-20250514":   _OPUS,

    # Sonnet 4 family
    "claude-sonnet-4-6":        _SONNET,
    "claude-sonnet-4-5":        _SONNET,
    "claude-sonnet-4-20250514": _SONNET,

    # Haiku 4 family
    "claude-haiku-4-5":             _HAIKU,
    "claude-haiku-4-5-20251001":    _HAIKU,
}

# Conservative default for unknown models: use Opus rates so we don't
# under-report cost on a model we haven't priced yet.
_DEFAULT_RATES = _OPUS


def get_rates(model: Optional[str]) -> dict[str, float]:
    """Return the per-Mtok rates dict for a model. Falls back to Opus."""
    if not model:
        return _DEFAULT_RATES
    return MODEL_PRICING.get(model.lower(), _DEFAULT_RATES)


def cost_usd(row: dict, model: Optional[str] = None) -> float:
    """Total USD cost for one invocation row.

    `row` should have the token columns from the index (or any dict-like with
    the same keys). `model` overrides row['model'] if you want to recompute.
    """
    rates = get_rates(model or row.get("model"))
    return (
        row.get("input_tokens", 0)      * rates["input"]
        + row.get("output_tokens", 0)     * rates["output"]
        + row.get("cache_read_tokens", 0) * rates["cache_read"]
        + row.get("cache_5m_tokens", 0)   * rates["cache_5m"]
        + row.get("cache_1h_tokens", 0)   * rates["cache_1h"]
    ) / 1_000_000


def cost_breakdown(row: dict, model: Optional[str] = None) -> dict[str, float]:
    """Per-component USD cost. Useful for pie charts."""
    rates = get_rates(model or row.get("model"))
    out = {
        "input":          row.get("input_tokens", 0)        * rates["input"]      / 1_000_000,
        "output":         row.get("output_tokens", 0)       * rates["output"]     / 1_000_000,
        "cache_read":     row.get("cache_read_tokens", 0)   * rates["cache_read"] / 1_000_000,
        "cache_5m":       row.get("cache_5m_tokens", 0)     * rates["cache_5m"]   / 1_000_000,
        "cache_1h":       row.get("cache_1h_tokens", 0)     * rates["cache_1h"]   / 1_000_000,
    }
    out["total"] = sum(out.values())
    return out


def known_models() -> list[str]:
    return sorted(MODEL_PRICING.keys())


def cost_per_skill(conn, days: Optional[int] = None) -> list[dict]:
    """Per-skill USD cost. Streams over skill_invocations, applies model rates."""
    from . import queries
    tf_sql, tf_params = queries.time_filter(days)
    rows = conn.execute(
        f"""
        SELECT skill_name, model, input_tokens, output_tokens,
               cache_read_tokens, cache_5m_tokens, cache_1h_tokens
        FROM skill_invocations
        WHERE 1=1 {tf_sql}
        """,
        tf_params,
    ).fetchall()
    totals: dict[str, dict] = {}
    for row in rows:
        d = dict(row)
        skill = d["skill_name"]
        slot = totals.setdefault(skill, {"skill_name": skill, "calls": 0, "cost_usd": 0.0})
        slot["calls"] += 1
        slot["cost_usd"] += cost_usd(d)
    return sorted(totals.values(), key=lambda x: -x["cost_usd"])


def _smoke(db_path: str = "/tmp/csm-smoke.db") -> None:
    from collections import defaultdict
    from . import db

    print("=== model rate table ===")
    for name, rates in MODEL_PRICING.items():
        print(f"  {name:<32}  in=${rates['input']:.2f}  out=${rates['output']:.2f}"
              f"  cache_r=${rates['cache_read']:.2f}"
              f"  cache_5m=${rates['cache_5m']:.2f}  cache_1h=${rates['cache_1h']:.2f}")

    print("\n=== cost of every indexed invocation (against current DB) ===")
    total_cost = 0.0
    by_skill: dict[str, float] = defaultdict(float)
    by_component: dict[str, float] = defaultdict(float)
    with db.connect(db_path) as conn:
        for row in conn.execute("SELECT * FROM skill_invocations"):
            d = dict(row)
            c = cost_usd(d)
            total_cost += c
            by_skill[d["skill_name"]] += c
            br = cost_breakdown(d)
            for k in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
                by_component[k] += br[k]

    print(f"\nTOTAL across all indexed invocations: ${total_cost:.4f}")

    print("\nBy skill (top 10):")
    for skill, c in sorted(by_skill.items(), key=lambda x: -x[1])[:10]:
        share = (c / total_cost * 100) if total_cost else 0
        print(f"  ${c:>8.4f}  ({share:>5.1f}%)  {skill}")

    print("\nBy component:")
    for k in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
        share = (by_component[k] / total_cost * 100) if total_cost else 0
        print(f"  ${by_component[k]:>8.4f}  ({share:>5.1f}%)  {k}")


if __name__ == "__main__":
    import sys
    _smoke(sys.argv[1] if len(sys.argv) >= 2 else "/tmp/csm-smoke.db")
