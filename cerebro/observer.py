import functools
from typing import Callable
from loguru import logger
from cerebro.storage import MemoryBank

_bank = None


def get_bank() -> MemoryBank:
    """Lazily initialize and return the singleton memory bank."""
    global _bank
    if _bank is None:
        _bank = MemoryBank()
    return _bank


def observe_brain(func: Callable):
    """Decorate an AI call with recall, commit, and failure learning."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bank = get_bank()

        prompt = args[0] if args else kwargs.get("prompt", "No prompt")

        past_memories = bank.retrieve(query_text=prompt)
        if past_memories:
            kwargs["context"] = "\n".join(past_memories)

        try:
            response = func(*args, **kwargs)

            bank.commit(
                text=str(response),
                metadata={"prompt": prompt, "utility_score": 0.5}
            )
            return response

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Cerebro caught a crash: {error_msg}")

            bank.commit(
                text=f"CRITICAL LESSON: For prompt '{prompt}', avoid previous mistakes. Error was: {error_msg}",
                metadata={"prompt": prompt, "utility_score": 1.0}
            )
            raise e

    return wrapper


def mark_as_bad(query_text: str) -> None:
    """Downvote the most similar memory to reduce future retrieval."""
    bank = get_bank()
    results = bank.collection.query(query_texts=[query_text], n_results=1)
    if results['ids'] and results['ids'][0]:
        mem_id = results['ids'][0][0]
        bank.update_score(mem_id, -1.0)
        logger.error(
            f"Cerebro learned a lesson: Discarding memory about '{query_text}'")
