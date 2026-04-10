from fastmcp import FastMCP
from cerebro.observer import get_bank

mcp = FastMCP("Cerebro-Memory-Engine")


@mcp.tool()
async def recall_context(task_description: str) -> str:
    """Resolve semantic context for active execution planning.

    This endpoint exposes Semantic Retrieval as a stable contract so downstream
    runtimes can consume historical context without coupling to storage internals.
    Deterministic formatting preserves interoperability across heterogeneous MCP
    clients.

    Args:
        task_description: Natural-language summary of the current objective.

    Returns:
        A formatted context block containing matched memories, or a fallback
        message when no relevant memory exists.

    Raises:
        RuntimeError: If the memory layer fails to execute retrieval.
    """
    bank = get_bank()
    memories = await bank.retrieve_weighted(task_description)
    if not memories:
        return "No specific context found."

    segments = [f"[{m['category'].upper()}] {d}" for d, m in memories]
    return "PERSISTENT CONTEXT:\n" + "\n".join(segments)


@mcp.tool()
async def record_pattern(pattern: str, category: str = "habit") -> str:
    """Persist a reusable behavioral signal into long-term memory lanes.

    Categorized persistence enables policy-aware retrieval where reinforced
    patterns can be weighted independently from episodic corrective lessons.

    Args:
        pattern: Behavior, preference, or lesson to persist.
        category: Memory lane for persistence. Use ``habit`` for weighted
            preference reinforcement; any other value is stored as a lesson.

    Returns:
        A status message describing persistence outcome and confidence when
        applicable.

    Raises:
        RuntimeError: If persistence fails in the underlying memory backend.
    """
    bank = get_bank()
    if category == "habit":
        strength = await bank.upsert_habit(pattern)
        return f"Pattern recorded. Confidence: {strength}"
    else:
        await bank.commit(pattern, {"category": "lesson"})
        return "Lesson persisted to vault."


@mcp.tool()
async def export_brain_dna() -> str:
    """Export the local memory graph for portability and recovery workflows.

    Export enables secure handoff between sessions or models without requiring a
    remote dependency. This aligns with local-first operation and provides an
    auditable backup mechanism for user memory state.

    Args:
        None.

    Returns:
        A status message containing the exported artifact path.

    Raises:
        RuntimeError: If vault export fails or the destination is unavailable.
    """
    bank = get_bank()
    path = await bank.export_vault()
    return f"DNA exported to: {path}"


@mcp.tool()
async def migrate_brain_dna(file_path: str) -> str:
    """Import an exported memory artifact into the active local vault.

    Migration supports continuity across model/runtime boundaries while keeping
    user memory ownership local. The operation is intentionally explicit to
    avoid accidental state mutation from implicit sync behavior.

    Args:
        file_path: Absolute or relative path to an exported vault artifact.

    Returns:
        A status message confirming migration completion.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        RuntimeError: If import validation or persistence fails.
    """
    bank = get_bank()
    await bank.import_vault(file_path)
    return "Migration complete. Previous habits absorbed."


def main() -> None:
    """Start the MCP server runtime.

    The entrypoint is isolated to keep module imports side-effect free for test
    harnesses and embedding scenarios.

    Args:
        None.

    Returns:
        None.

    Raises:
        RuntimeError: If server bootstrap fails.
    """
    mcp.run()


if __name__ == "__main__":
    main()
