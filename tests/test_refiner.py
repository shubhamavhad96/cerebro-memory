"""Refiner smoke tests."""

from __future__ import annotations

from cerebro.core.refiner import SecretRefiner


def test_secret_refiner_masks_assignments() -> None:
    refiner = SecretRefiner(enabled=True)
    raw = "OPENAI_API_KEY=sk-test-value\nOTHER=ok\n"
    out = refiner.clean_text(raw)
    assert "[REDACTED_SECRET]" in out
    assert "sk-test-value" not in out
