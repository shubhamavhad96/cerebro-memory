import functools
from typing import Callable
from loguru import logger
from cerebro.storage import MemoryBank

# Remove the line: bank = MemoryBank()
_bank = None


def get_bank():
    global _bank
    if _bank is None:
        _bank = MemoryBank()
    return _bank


def observe_brain(func: Callable):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get the bank only when we actually run the function
        bank = get_bank()

        prompt = args[0] if args else kwargs.get("prompt", "No prompt")

        # 1. RECALL
        past_memories = bank.retrieve(query_text=prompt)
        if past_memories:
            kwargs["context"] = "\n".join(past_memories)

        try:
            response = func(*args, **kwargs)

            # 2. COMMIT (Success)
            bank.commit(
                text=str(response),
                metadata={"prompt": prompt, "utility_score": 0.5}
            )
            return response

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Cerebro caught a crash: {error_msg}")

            # 3. SELF-HEALING: Store the lesson
            bank.commit(
                text=f"CRITICAL LESSON: For prompt '{prompt}', avoid previous mistakes. Error was: {error_msg}",
                metadata={"prompt": prompt, "utility_score": 1.0}
            )
            raise e

    return wrapper


def mark_as_bad(query_text: str):
    """Finds the last retrieved memory for a topic and downvotes it."""
    results = bank.collection.query(query_texts=[query_text], n_results=1)
    if results['ids'] and results['ids'][0]:
        mem_id = results['ids'][0][0]
        bank.update_score(mem_id, -1.0)  # The 'Red Marker'
        logger.error(
            f"Cerebro learned a lesson: Discarding memory about '{query_text}'")
