import asyncio
from typing import Any, List

from cerebro.distiller import distill_habits
from cerebro.observer import get_bank, observe_brain
from cerebro.storage import MemoryBank
from loguru import logger


@observe_brain
async def habit_ingestor(prompt: str, **kwargs: Any) -> str:
    """Simple agent to feed habits into the vault.

    Accepts arbitrary keyword arguments so ``observe_brain`` can inject
    ``context`` without raising ``TypeError``.
    """
    return f"Acknowledged: {prompt}"


async def _wipe_vault_categories(bank: MemoryBank, categories: List[str]) -> None:
    """Remove all records in the given metadata categories for an isolated test run.

    Args:
        bank: Active memory bank instance.
        categories: ``category`` metadata values to clear (e.g. ``habit``, ``cache``).

    Returns:
        None.

    Raises:
        None.
    """
    ids: List[str] = []
    seen: set[str] = set()
    for cat in categories:
        for row in await bank.get_all_by_category(cat):
            hid = str(row["id"])
            if hid not in seen:
                seen.add(hid)
                ids.append(hid)
    await bank.prune_memories(ids)
    logger.info(
        "Vault reset: removed {} record(s) across categories {}.",
        len(ids),
        categories,
    )


async def main() -> None:
    bank = get_bank()

    await _wipe_vault_categories(bank, ["habit", "cache"])

    # Varied wording keeps pairwise cache distances above the 0.05 hit threshold
    # while remaining semantically close for distiller clustering (0.4 graph edge).
    similar_habits = [
        "Python style H1: use literal tab characters per indent level, not space runs.",
        "Editor policy for *.py: insert U+0009 when increasing indentation depth.",
        "Code review: when editing Python, keep tab-based indentation unchanged.",
        "Team onboarding — our Python services standardize on tabs, not spaces.",
        "Refactor constraint: do not convert existing tab indents to spaces in .py files.",
    ]

    logger.info("--- Phase 1: Ingesting semantically aligned habits (cache-safe prompts) ---")
    for habit in similar_habits:
        await habit_ingestor(habit)

    habits_before_distill = await bank.get_all_by_category("habit")
    new_habit_count = len(habits_before_distill)
    logger.info(
        "Phase 2 pre-check: {} new habit record(s) persisted after ingest "
        "(vault habit/cache cleared at start; varied prompts avoid semantic cache hits).",
        new_habit_count,
    )

    logger.info("--- Phase 2: Triggering Manual Distillation ---")
    await distill_habits()

    final_habits = await bank.get_all_by_category("habit")
    logger.success(f"Final habit record count: {len(final_habits)}")

    if len(final_habits) < len(habits_before_distill):
        for habit in final_habits:
            doc = habit["document"]
            logger.info(f"Distilled Master Habit (record): {doc}")
        logger.success(
            "VERIFIED: Multiple habit records consolidated into a high-density entry."
        )
    else:
        logger.error(
            "FAILURE: Distillation did not reduce the habit record count."
        )


if __name__ == "__main__":
    asyncio.run(main())
