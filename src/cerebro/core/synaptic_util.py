"""Senior Architect module: synaptic utility helpers."""

from __future__ import annotations


def safe_ratio(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return a / b
