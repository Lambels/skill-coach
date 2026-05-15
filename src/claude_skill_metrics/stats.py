"""Statistical helpers built on stdlib `statistics`.

Pure math. No DB, no I/O. Used by queries.py and (eventually) the coach.
"""

from __future__ import annotations

import statistics
from typing import Iterable


def mean(values: Iterable[float]) -> float:
    vs = list(values)
    return statistics.fmean(vs) if vs else 0.0


def stddev(values: Iterable[float]) -> float:
    """Population standard deviation. 0 for n < 2."""
    vs = list(values)
    return statistics.pstdev(vs) if len(vs) >= 2 else 0.0


def percentile(values: Iterable[float], p: int) -> float:
    """The p-th percentile (1..99). Inclusive method, matches NumPy default."""
    vs = list(values)
    if not vs:
        return 0.0
    if len(vs) == 1:
        return float(vs[0])
    qs = statistics.quantiles(sorted(vs), n=100, method="inclusive")
    return qs[p - 1]


def percentiles(values: Iterable[float], ps: list[int]) -> dict[int, float]:
    """Multiple percentiles from one sorted pass."""
    vs = list(values)
    if not vs:
        return {p: 0.0 for p in ps}
    if len(vs) == 1:
        return {p: float(vs[0]) for p in ps}
    qs = statistics.quantiles(sorted(vs), n=100, method="inclusive")
    return {p: qs[p - 1] for p in ps}


def p50(values: Iterable[float]) -> float:
    return percentile(values, 50)


def p95(values: Iterable[float]) -> float:
    return percentile(values, 95)


def p99(values: Iterable[float]) -> float:
    return percentile(values, 99)


def cache_hit_ratio(
    uncached_input: int,
    cache_read: int,
    cache_creation: int,
) -> float:
    """Fraction of input tokens served from cache. 0.0 if no input at all."""
    total = uncached_input + cache_read + cache_creation
    return (cache_read / total) if total else 0.0


def effective_input_tokens(
    uncached_input: int,
    cache_read: int,
    cache_creation: int,
    cache_read_rate: float = 0.10,
    cache_creation_rate: float = 1.25,
) -> float:
    """Tokens normalised to the uncached-input billing rate.

    Anthropic charges (roughly): cache_read at 10% of input rate,
    cache_creation at 125%. This collapses the three input streams into
    a single 'equivalent uncached input tokens' figure for cost ranking.
    """
    return (
        uncached_input
        + cache_read * cache_read_rate
        + cache_creation * cache_creation_rate
    )


def _smoke() -> None:
    vs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]
    print("sample [1,2,...,10,100]")
    print(f"  mean       = {mean(vs):>7.2f}")
    print(f"  stddev     = {stddev(vs):>7.2f}")
    print(f"  p50        = {p50(vs):>7.2f}   (median)")
    print(f"  p95        = {p95(vs):>7.2f}")
    print(f"  p99        = {p99(vs):>7.2f}")
    print(f"  max        = {max(vs):>7}")
    print()
    print("empty list → all zeros, no crash")
    print(f"  mean([])   = {mean([])}")
    print(f"  p50([])    = {p50([])}")
    print(f"  stddev([]) = {stddev([])}")
    print()
    print("cache + cost helpers")
    print(f"  cache_hit_ratio(100, 800, 50)    = {cache_hit_ratio(100, 800, 50):.4f}")
    print(f"  effective_input(100, 800, 50)    = {effective_input_tokens(100, 800, 50):.2f}")
    print(f"  effective_input(0, 30000, 0)     = {effective_input_tokens(0, 30000, 0):.2f}")


if __name__ == "__main__":
    _smoke()
