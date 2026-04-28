"""
MCP server spoke for banking architectural intent into Cerebro's local queue.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import fcntl
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Cerebro")


@mcp.tool()
def save_architectural_intent(intent: str, reasoning: str, workspace_root: str) -> str:
    """
    Persist one architectural decision + reasoning entry to `.cerebro/intent_queue.json`.

    You MUST pass the absolute path of the user's current project/workspace as
    the workspace_root parameter.
    """
    target_dir = os.path.join(workspace_root, ".cerebro")
    queue_path = os.path.join(target_dir, "intent_queue.json")
    entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "intent": intent,
        "reasoning": reasoning,
    }

    os.makedirs(target_dir, exist_ok=True)

    # Use a single locked read-append-write cycle to prevent corruption when
    # multiple tool invocations happen concurrently.
    with open(queue_path, "a+", encoding="utf-8") as file_obj:
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
        try:
            file_obj.seek(0)
            raw = file_obj.read().strip()
            if not raw:
                queue: list[dict[str, str]] = []
            else:
                try:
                    parsed = json.loads(raw)
                    queue = parsed if isinstance(parsed, list) else []
                except json.JSONDecodeError:
                    queue = []

            queue.append(entry)
            file_obj.seek(0)
            file_obj.truncate()
            json.dump(queue, file_obj, ensure_ascii=False, indent=2)
            file_obj.write("\n")
            file_obj.flush()
            os.fsync(file_obj.fileno())
        finally:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)

    return f"Architectural intent securely banked in {queue_path}."


if __name__ == "__main__":
    mcp.run()
