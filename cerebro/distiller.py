"""Semantic clustering and Context Density compaction for habit memories."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable, DefaultDict, Dict, List

from loguru import logger
from ollama import AsyncClient

from cerebro.storage import MemoryBank

_CLUSTER_DISTANCE_THRESHOLD = 1.25
_MIN_CLUSTER_SIZE_FOR_DISTILL = 2

_SYNTHESIS_HEADER = (
    "Below are multiple observed habits of the user. Merge them into a single, "
    "high-density declarative statement that captures the core behavior. No fluff."
)


def _union_find_merge(parent: Dict[str, str], a: str, b: str) -> None:
    """Union two ids in a disjoint-set structure (path compression on find).

    Args:
        parent: Map from id to parent id.
        a: First habit id.
        b: Second habit id.

    Returns:
        None.

    Raises:
        None.
    """

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ra, rb = _find(a), _find(b)
    if ra != rb:
        parent[rb] = ra


def _preview_for_log(text: str, max_len: int = 160) -> str:
    """Collapse whitespace and cap length for dense debug lines.

    Args:
        text: Raw habit document string.
        max_len: Maximum characters before truncation.

    Returns:
        Single-line preview suitable for log output.

    Raises:
        None.
    """
    t = " ".join(str(text).split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


async def distill_habits() -> None:
    """Compact redundant habit rows via Semantic Clustering and LLM synthesis.

    Habits within the same connected component under a vector-distance graph
    (distance threshold ``1.25``) and with component size strictly greater than
    one (i.e. at least two habit records) are merged into one high-density declarative
    record. Aggregate ``strength`` preserves reinforcement mass. Old members are
    removed only after the distilled row is persisted (atomic compaction).

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    from cerebro.observer import call_llm, get_bank

    try:
        await _distill_habits_core(call_llm, get_bank)
    except Exception:
        logger.exception("Habit distillation job failed.")


async def _distill_habits_core(
    call_llm_fn: Callable[..., Awaitable[str]],
    get_bank_fn: Callable[[], MemoryBank],
) -> None:
    """Run one distillation pass (internal; errors propagate to ``distill_habits``).

    Args:
        call_llm_fn: Bound ``call_llm`` implementation from the observer layer.
        get_bank_fn: ``get_bank`` accessor for the process singleton.

    Returns:
        None.

    Raises:
        RuntimeError: If storage or model I/O fails.
    """
    bank = get_bank_fn()
    habits: List[Dict[str, Any]] = await bank.get_all_by_category("habit")
    if len(habits) < _MIN_CLUSTER_SIZE_FOR_DISTILL:
        return

    parent: Dict[str, str] = {h["id"]: h["id"] for h in habits}
    id_to_habit = {h["id"]: h for h in habits}
    n_habits = len(habits)

    loop = asyncio.get_running_loop()
    for h in habits:
        doc = h.get("document") or ""
        results = await loop.run_in_executor(
            None,
            lambda d=doc: bank.collection.query(
                query_texts=[d],
                n_results=max(n_habits, 1),
                where={"category": "habit"},
            ),
        )
        row_ids = results.get("ids", [[]])[0] or []
        dists = results.get("distances", [[]])[0] or []
        for rid, dist in zip(row_ids, dists):
            if rid is None or dist is None:
                continue
            if rid not in id_to_habit:
                continue
            neighbor_doc = str(id_to_habit[rid].get("document") or "")
            dval = float(dist)
            logger.debug(
                "Habit: {} | Neighbor: {} | Distance: {}",
                _preview_for_log(doc),
                _preview_for_log(neighbor_doc),
                dval,
            )
            if dval >= _CLUSTER_DISTANCE_THRESHOLD:
                continue
            _union_find_merge(parent, h["id"], rid)

    def _root(hid: str) -> str:
        while parent[hid] != hid:
            parent[hid] = parent[parent[hid]]
            hid = parent[hid]
        return hid

    clusters: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for h in habits:
        clusters[_root(h["id"])].append(h)

    logger.debug(
        "Semantic clustering: {} connected component(s); per-component sizes (sorted): {}",
        len(clusters),
        sorted(len(m) for m in clusters.values()),
    )

    client = AsyncClient()
    model = "llama3"

    for _root_key, members in sorted(clusters.items(), key=lambda x: x[0]):
        if len(members) < _MIN_CLUSTER_SIZE_FOR_DISTILL:
            continue

        total_strength = 0
        lines: List[str] = []
        member_ids: List[str] = []
        for m in members:
            member_ids.append(str(m["id"]))
            meta = m.get("metadata") or {}
            try:
                total_strength += int(float(meta.get("strength", 1)))
            except (TypeError, ValueError):
                total_strength += 1
            lines.append(str(m.get("document") or "").strip())

        body = "\n".join(f"- {t}" for t in lines if t)
        full_prompt = f"{_SYNTHESIS_HEADER}\n\n{body}"

        try:
            raw_out = await call_llm_fn(client, model, full_prompt, "")
        except Exception as exc:
            logger.warning(
                "Distillation synthesis failed: LLM raised {} for cluster size={}: {!r}",
                type(exc).__name__,
                len(members),
                exc,
            )
            continue

        distilled = (raw_out or "").strip()
        if not distilled:
            logger.warning(
                "Distillation synthesis failed: empty or whitespace-only model output "
                "(cluster_size={}, raw_type={}, prompt_char_len={}).",
                len(members),
                type(raw_out).__name__,
                len(full_prompt),
            )
            continue

        await bank.commit(
            distilled,
            {
                "category": "habit",
                "strength": total_strength,
            },
        )
        await bank.prune_memories(member_ids)
        logger.info(
            "Habit distillation: merged {} rows into one master habit (aggregate strength={}).",
            len(members),
            total_strength,
        )
