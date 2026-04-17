"""Aggregate scores across eval runs."""

from __future__ import annotations

from typing import List, Sequence


def pass_rate(passed: Sequence[bool]) -> float:
    if not passed:
        return 0.0
    return sum(1 for p in passed if p) / len(passed)


def mean(scores: Sequence[float]) -> float:
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def pass_at_least_once(results: List[bool]) -> bool:
    return any(results)
