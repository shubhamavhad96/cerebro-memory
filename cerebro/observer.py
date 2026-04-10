import functools
import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, TypeVar, cast
from ollama import AsyncClient
from loguru import logger
from cerebro.storage import MemoryBank
from cerebro.security import scrub_sensitive_data
from cerebro.distiller import distill_habits

T = TypeVar("T")
_bank: Optional[MemoryBank] = None
_successful_interaction_count: int = 0
_DISTILLATION_INTERVAL: int = 50


def _schedule_distillation_if_due() -> None:
    """Fire-and-forget habit distillation on a fixed interaction cadence.

    Invoked only after a successful write path (vault commits). Semantic cache
    hits are read-only and do not advance this counter or schedule distillation.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    global _successful_interaction_count
    _successful_interaction_count += 1
    if _successful_interaction_count % _DISTILLATION_INTERVAL == 0:
        asyncio.create_task(distill_habits())


def _habit_worth_persisting(habit_text: str) -> bool:
    """Return whether a profiler habit line should be written to the vault.

    Drops explicit opt-outs and single-token meta-talk that pollutes clustering.

    Args:
        habit_text: Scrubbed habit string from the profiler model.

    Returns:
        ``True`` if the habit should be passed to ``upsert_habit``.

    Raises:
        None.
    """
    normalized = " ".join(str(habit_text).split()).strip()
    if not normalized:
        return False
    if normalized.upper() == "NONE":
        return False
    words = normalized.split()
    if len(words) == 1 and words[0].lower() in frozenset({"acknowledged", "none"}):
        return False
    return True


def get_bank() -> MemoryBank:
    """Return the process-level memory bank singleton.

    Centralizing allocation prevents duplicate vector clients in concurrent
    workflows and keeps memory state consistent across decorators and MCP tools.

    Args:
        None.

    Returns:
        Shared memory bank instance.

    Raises:
        RuntimeError: If the memory bank cannot be initialized.
    """
    global _bank
    if _bank is None:
        _bank = MemoryBank()
    return _bank


async def call_llm(client: Any, model: str, prompt: str, system: str = "") -> str:
    """Normalize LLM invocation across heterogeneous async client interfaces.

    The adapter isolates provider-specific response formats so higher-level
    orchestration logic can remain provider-agnostic and deterministic.

    Args:
        client: Async LLM client implementing either chat-completions or
            generate-style APIs.
        model: Model identifier passed through to the provider.
        prompt: User/task prompt payload.
        system: Optional system instruction for policy framing.

    Returns:
        Model-generated text payload.

    Raises:
        RuntimeError: If upstream model invocation fails.
    """
    if hasattr(client, 'chat') and hasattr(client.chat, 'completions'):
        res = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}]
        )
        return res.choices[0].message.content
    else:
        res = await client.generate(model=model, prompt=prompt, system=system)
        return res['response']


def observe_brain(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorate an async task with Chain-of-Memory context synthesis.

    The decorator performs recursive retrieval, strategic context synthesis, and
    post-execution auditing to continuously refine memory quality. This enforces
    self-correcting behavior while preserving transparent context injection.

    Args:
        func: Async callable representing the primary model execution path.

    Returns:
        Wrapped async callable with retrieval, critique, and persistence stages.

    Raises:
        RuntimeError: Propagates failures from retrieval, synthesis, or storage.
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        """Execute the full recursive memory orchestration lifecycle.

        Args:
            *args: Positional arguments forwarded to the wrapped callable.
            **kwargs: Keyword arguments forwarded to the wrapped callable.

        Returns:
            Wrapped callable result after context enrichment and policy checks.

        Raises:
            ValueError: If the critic marks output as invalid.
            RuntimeError: If retrieval, synthesis, or persistence fails.
        """
        bank = get_bank()
        prompt = args[0] if args else kwargs.get("prompt", "No prompt")
        vault_prompt = scrub_sensitive_data(str(prompt))
        client = AsyncClient()

        cached = await bank.check_cache(vault_prompt)
        if cached is not None:
            logger.info("Semantic Cache Hit | 0ms Latency")
            return cast(T, cached)

        primary = await bank.retrieve_weighted(vault_prompt, n_results=3)
        related_tasks = [
            bank.retrieve_weighted(scrub_sensitive_data(str(m[0])), n_results=2)
            for m in primary
        ]
        secondary_results = await asyncio.gather(*related_tasks)

        seen_docs: Set[str] = set()
        unique_memories: List[Tuple[str, Dict[str, Any]]] = []
        for doc, meta in (primary + [m for sub in secondary_results for m in sub]):
            if doc not in seen_docs:
                unique_memories.append((doc, meta))
                seen_docs.add(doc)

        mem_text = "\n".join(
            [
                f"[{m['category']}] {scrub_sensitive_data(d)}"
                for d, m in unique_memories
            ]
        )
        synthesis_prompt = (
            f"TASK: {vault_prompt}\n\nHISTORY:\n{mem_text}\n\n"
            "Create a 1-paragraph 'Strategic Briefing' note. Summarize user intent, "
            "past project DNA, and avoidances. No bullets."
        )
        briefing = await call_llm(client, 'llama3', synthesis_prompt)

        kwargs["context"] = (
            "\n--- STRATEGIC RESEARCH BRIEFING ---\n"
            f"{briefing}\n\n"
            "TRANSPARENCY PROTOCOL: Disclose if you are following a specific pattern from this briefing."
        )

        try:
            response = await func(*args, **kwargs)
            vault_response = scrub_sensitive_data(str(response))

            critic_system = (
                "You are a Logic Gate. Your only job is to stop malicious content "
                "(malware, hate speech) or clear logical contradictions.\n"
                "- Standard coding preferences, habits, and normal conversation are always a 'PASS'.\n"
                "- Output ONLY the word 'PASS' if the interaction is safe/normal.\n"
                "- Output 'FAIL: [reason]' ONLY if there is a serious safety or logic violation."
            )
            profiler_system = (
                "Instructions: Summarize the user's core preference or habit in under 10 words. "
                "Output ONLY the declarative habit statement. Do NOT include preambles like "
                "'Acknowledged', 'The user prefers', or 'Here is the line'. "
                "If no clear habit is present, output 'NONE'."
            )
            critic_task = call_llm(
                client,
                "llama3",
                f"Prompt: {vault_prompt}\nResp: {vault_response}",
                critic_system,
            )
            profiler_task = call_llm(
                client,
                "llama3",
                f"Prompt: {vault_prompt}\nResp: {vault_response}",
                profiler_system,
            )

            audit, habit_note = await asyncio.gather(critic_task, profiler_task)

            audit_text = audit.strip()
            audit_upper = audit_text.upper()
            if audit_upper.startswith("PASS"):
                pass
            elif audit_upper.startswith("FAIL"):
                raise ValueError(f"CRITIC REJECTION: {audit}")
            else:
                logger.warning(
                    "Critic returned non-binary output; failing open (treating as PASS). "
                    "preview={!r}",
                    audit_text[:500],
                )

            habit_vault = scrub_sensitive_data(habit_note.strip())
            convo_snippet = vault_response[:200]
            persist_tasks: List[Any] = [
                bank.commit(
                    f"CONVERSATION: User asked '{vault_prompt}' | AI: '{convo_snippet}...'",
                    {"category": "conversation"},
                ),
                bank.commit(
                    vault_prompt,
                    {
                        "category": "cache",
                        "cached_response": vault_response,
                    },
                ),
            ]
            if _habit_worth_persisting(habit_vault):
                persist_tasks.insert(0, bank.upsert_habit(habit_vault))
            await asyncio.gather(*persist_tasks)
            _schedule_distillation_if_due()
            return response

        except Exception as e:
            logger.error(f"Cerebro Logic Failure: {e}")
            err_vault = scrub_sensitive_data(str(e))
            await bank.commit(
                f"CRITICAL LESSON: '{vault_prompt}' failed. Error: {err_vault}",
                {"category": "lesson"},
            )
            raise e

    return wrapper
