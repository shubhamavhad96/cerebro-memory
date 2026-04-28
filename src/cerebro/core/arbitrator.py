"""Senior Architect module: arbitration utilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ArbitrationResult:
    winner: str
    confidence: float = 0.0


def choose_winner(candidates: list[str]) -> ArbitrationResult:
    if not candidates:
        return ArbitrationResult(winner="none", confidence=0.0)
    return ArbitrationResult(winner=candidates[0], confidence=1.0)
