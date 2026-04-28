"""
Terminal proxy spoke: capture CLI intent, then exec the original tool.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from datetime import datetime, timezone


def intercept_and_run(command_args: tuple) -> None:
    """
    Capture raw terminal intent to `.cerebro/intent_queue.json`, then exec target.
    """
    if not command_args:
        raise SystemExit("No command provided to proxy.")

    intent = " ".join(str(part) for part in command_args).strip()
    root = os.getcwd()
    target_dir = os.path.join(root, ".cerebro")
    queue_path = os.path.join(target_dir, "intent_queue.json")
    os.makedirs(target_dir, exist_ok=True)

    entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "intent": intent,
        "reasoning": "Captured via Terminal Proxy",
    }

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

    try:
        os.execvp(str(command_args[0]), [str(arg) for arg in command_args])
    except FileNotFoundError:
        sys.stderr.write(f"cerebro: command not found: {command_args[0]}\n")
        sys.exit(127)

    # Unreachable on success; keeps type-checkers happy.
    raise SystemExit(0)

