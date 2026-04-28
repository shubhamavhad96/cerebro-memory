"""
Router spoke for draining pending architectural intents into compiler input text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_pending_intents(root_dir: Path | str) -> str:
    """
    Drain `.cerebro/intent_queue.json` and return formatted intent text.

    Returns an empty string when the queue file is missing, empty, unreadable, or
    does not contain a JSON array payload.
    """
    root = Path(root_dir)
    queue_path = root / ".cerebro" / "intent_queue.json"
    if not queue_path.exists():
        return ""

    try:
        raw = queue_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not raw:
        return ""

    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, list) or not payload:
        return ""

    blocks: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        ts = str(item.get("timestamp_utc", "")).strip()
        intent = str(item.get("intent", "")).strip()
        reasoning = str(item.get("reasoning", "")).strip()
        blocks.append(f"[{ts}] Intent: {intent}\nReasoning: {reasoning}")

    if not blocks:
        return ""

    formatted = "\n\n---\n\n".join(blocks)
    try:
        queue_path.write_text("[]\n", encoding="utf-8")
    except OSError:
        # If draining fails, do not emit data to avoid reprocessing ambiguity.
        return ""
    return formatted
