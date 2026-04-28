"""SQLite schema and access layer for queued compiler events (WAL, busy timeout).

All persistent state lives under ``.cerebro/`` at the repository root so hooks,
CLI, and IDEs agree on a single directory without polluting the project tree.
"""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    """
    Return an RFC 3339-like UTC timestamp string for event ordering.

    Returns:
        str: ISO 8601 timestamp in UTC.
    """
    return datetime.now(timezone.utc).isoformat()


def resolve_repo_root() -> Path:
    """
    Resolve the git working tree top level via ``git rev-parse``.

    Falls back to ``Path.cwd()`` when not inside a repo or git is unavailable,
    so CLI and hooks behave predictably in non-git contexts.

    Returns:
        Path: Absolute repository root or current working directory.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
        )
        line = (proc.stdout or "").strip().splitlines()
        if line:
            return Path(line[0]).resolve()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return Path.cwd().resolve()


def default_db_path(project_root: Path | None = None) -> Path:
    """
    Return the canonical SQLite database path: ``<root>/.cerebro/hippocampus.db``.

    Colocates the event queue with ``KNOWLEDGE_GRAPH.md`` under ``.cerebro/`` for
    a single auditable privacy boundary.

    Args:
        project_root: Optional repository root; defaults to ``resolve_repo_root()``.

    Returns:
        Path: Absolute path to ``hippocampus.db``.
    """
    root = project_root.resolve() if project_root else resolve_repo_root()
    return root / ".cerebro" / "hippocampus.db"


_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      message TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS synapses (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      source TEXT NOT NULL,
      relation TEXT NOT NULL,
      target TEXT NOT NULL,
      evidence TEXT NOT NULL DEFAULT ''
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);",
    "CREATE INDEX IF NOT EXISTS idx_synapses_ts ON synapses(ts);",
    "CREATE INDEX IF NOT EXISTS idx_synapses_source ON synapses(source);",
    "CREATE INDEX IF NOT EXISTS idx_synapses_target ON synapses(target);",
)


@dataclass(slots=True)
class SqliteHippocampus:
    """
    Facade over the events queue stored in SQLite.

    Initializes schema once per process, enables WAL and a bounded busy
    timeout on every connection to survive concurrent hook and CLI access.

    Attributes:
        db_path: Absolute path to ``hippocampus.db`` (parent dirs created on connect).
    """

    db_path: Path
    _schema_initialized: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path = self.db_path.resolve()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        """
        Open a new connection with project-local durability settings.

        Returns:
            sqlite3.Connection: Row-factory connection with WAL enabled.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _ensure_schema(self) -> None:
        """Apply DDL idempotently if not already applied for this instance."""
        if self._schema_initialized:
            return
        with self._connect() as conn:
            cur = conn.cursor()
            for stmt in _DDL:
                cur.execute(stmt)
            conn.commit()
        self._schema_initialized = True

    def log_event(self, message: str, ts: str | None = None) -> int:
        """
        Append one raw compiler event row (hook or CLI).

        Args:
            message: Non-empty event body (e.g. manual operator notes for ``cerebro log``).
            ts: Optional ISO timestamp; default is current UTC.

        Returns:
            int: SQLite ``rowid`` of the inserted event.

        Raises:
            ValueError: If ``message`` is empty after strip.
        """
        msg = str(message or "").strip()
        if not msg:
            raise ValueError("event message must be non-empty")
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO events(ts, message) VALUES(?, ?)",
                (ts or _now_iso(), msg),
            )
            conn.commit()
            return int(cur.lastrowid)

    def fetch_events(self, limit: int = 500) -> list[dict[str, Any]]:
        """
        Read the newest queued events up to ``limit`` (descending by id).

        Args:
            limit: Maximum rows; coerced to at least 1.

        Returns:
            list[dict[str, Any]]: Rows with keys ``id``, ``ts``, ``message``.
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, ts, message FROM events ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
            rows = cur.fetchall()
        return [
            {"id": int(row["id"]), "ts": str(row["ts"]), "message": str(row["message"])}
            for row in rows
        ]

    def clear_events(self) -> int:
        """
        Delete all rows from ``events`` after a successful compile.

        Returns:
            int: Row count before deletion (number of cleared events).
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(1) AS c FROM events")
            before = int(cur.fetchone()["c"])
            cur.execute("DELETE FROM events")
            conn.commit()
            return before
