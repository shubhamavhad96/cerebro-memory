"""End-to-end check that vault persistence receives scrubbed payloads only."""

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from cerebro.observer import get_bank, observe_brain


@observe_brain
async def security_agent(prompt: str, context: str = "") -> str:
    """Minimal agent surface used to exercise the observer persistence path.

    Args:
        prompt: Raw user text (must remain unmodified for the wrapped callable).
        context: Injected briefing context from the observer.

    Returns:
        Short acknowledgment string for deterministic downstream inspection.

    Raises:
        None.
    """
    return f"I processed your request regarding: {prompt[:30]}..."


def _select_conversation_document(
    memories: List[Tuple[str, Dict[str, Any]]],
) -> Optional[str]:
    """Pick the best document string to audit for redaction markers.

    Semantic ranking may surface non-conversation rows first; prefer explicit
    ``category == "conversation"`` when present.

    Args:
        memories: Ranked ``(document, metadata)`` pairs from ``retrieve_weighted``.

    Returns:
        Document text to inspect, or ``None`` if the list is empty.

    Raises:
        None.
    """
    for doc, meta in memories:
        if meta.get("category") == "conversation":
            return doc
    if memories:
        return memories[0][0]
    return None


async def main() -> None:
    """Drive a sensitive prompt through the observer and audit persisted text.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    bank = get_bank()

    sensitive_prompt = (
        "My private email is shubham.test@gmail.com and my AWS key is sk-1234567890abcdef."
    )

    logger.info("--- Phase 1: Ingesting sensitive prompt (vault must not store raw secrets) ---")
    await security_agent(prompt=sensitive_prompt)
    logger.success("Observer pipeline completed for ingest phase.")

    logger.info("--- Phase 2: Vault audit (semantic retrieval + redaction markers) ---")

    memories = await bank.retrieve_weighted(
        "private email conversation vault",
        n_results=10,
    )
    stored_text = _select_conversation_document(memories)

    if not stored_text:
        logger.warning(
            "No retrievable memories matched the audit query; verify commits and vault state."
        )
        return

    logger.info(f"Audit sample (truncated): {stored_text[:200]}...")

    if "[EMAIL_REDACTED]" in stored_text and "[API_KEY_REDACTED]" in stored_text:
        logger.success(
            "VERIFIED: Vault-held text contains expected redaction tokens for email and API-shaped secrets."
        )
    else:
        logger.error(
            "FAILURE: Expected redaction markers missing from vault-visible document text."
        )


if __name__ == "__main__":
    asyncio.run(main())
