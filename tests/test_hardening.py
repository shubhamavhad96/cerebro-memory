"""Hardening tests for Cerebro 3.0 edge cases."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from cerebro.adapters import cursor_adapter
from cerebro.core.compiler import truncate_payload


def test_sqlite_retry_succeeds_on_third_attempt() -> None:
    db_path = Path("/tmp/state.vscdb")
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = ('{"tabs":[]}',)

    with patch.object(
        cursor_adapter.sqlite3,
        "connect",
        side_effect=[
            sqlite3.OperationalError("locked-1"),
            sqlite3.OperationalError("locked-2"),
            conn,
        ],
    ) as connect_mock, patch.object(cursor_adapter.time, "sleep") as sleep_mock:
        out = cursor_adapter._query_item_value_ro(db_path, "workbench.panel.aichat.view.aichat.chatdata")

    assert out == '{"tabs":[]}'
    assert connect_mock.call_count == 3
    assert sleep_mock.call_count == 2
    sleep_mock.assert_called_with(0.5)


def test_truncate_payload_strips_package_lock_diff_and_shrinks() -> None:
    large_lock_body = "x" * 10_000
    app_body = "print('hello from app')\n"
    diff_text = (
        "diff --git a/package-lock.json b/package-lock.json\n"
        "--- a/package-lock.json\n"
        "+++ b/package-lock.json\n"
        "@@ -1 +1 @@\n"
        f"+{large_lock_body}\n"
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -0,0 +1 @@\n"
        f"+{app_body}"
    )
    original_len = len(diff_text)

    out_diff, out_chat = truncate_payload(diff_text, "", max_chars=5_000)

    assert out_chat == ""
    assert "package-lock.json" not in out_diff
    assert "diff --git a/app.py b/app.py" in out_diff
    assert len(out_diff) < original_len


def test_truncate_payload_hard_limit_24000_chars() -> None:
    huge_chat = "a" * 50_000

    out_diff, out_chat = truncate_payload("", huge_chat, max_chars=24_000)

    assert len(out_diff) + len(out_chat) <= 24_000
    assert len(out_chat) == 24_000
