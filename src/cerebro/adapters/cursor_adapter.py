"""
Locate and parse local Cursor / VS Code family workspace chat storage.

Primary sources: per-workspace ``state.vscdb`` (``ItemTable``) under the editor's
``User/workspaceStorage/`` tree. Open read-only, tolerate lock races.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# ItemTable keys seen in the wild (Cursor aichat + composer). Either may hold bubbles.
_AICHAT_KEY = "workbench.panel.aichat.view.aichat.chatdata"
_COMPOSER_KEY = "composer.composerData"


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """One user/assistant line with an optional source timestamp (UTC or naive)."""

    ts: datetime | None
    role: str  # "user" or "assistant"
    text: str


def _cursor_config_home() -> Path:
    if env := os.environ.get("CEREBRO_CURSOR_CONFIG", "").strip():
        return Path(env).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Cursor"
    if sys.platform == "darwin":
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        p = xdg / "Cursor"
        if p.is_dir():
            return p
        return Path.home() / "Library" / "Application Support" / "Cursor"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "Cursor"


def _workspace_storage_root() -> Path:
    return _cursor_config_home() / "User" / "workspaceStorage"


def _normalize_folder_uri(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if s.startswith("file://"):
        path = urllib.parse.unquote(urllib.parse.urlparse(s).path)
        if sys.platform == "win32" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return os.path.realpath(os.path.normcase(path))
    p = Path(s).expanduser()
    if p.is_dir():
        return os.path.realpath(os.path.normcase(str(p)))
    return None


def _read_workspace_json_folders(wsj: Path) -> list[str]:
    if not wsj.is_file():
        return []
    try:
        data = json.loads(wsj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    out: list[str] = []

    folder_entries: list[Any] = []
    # Cursor/VS Code workspace.json can use either a single `folder` entry
    # or a `folders` array; both may be URI strings or objects with `path`/`uri`.
    single_folder = data.get("folder")
    if isinstance(single_folder, (str, dict)):
        folder_entries.append(single_folder)
    folders = data.get("folders")
    if isinstance(folders, list):
        folder_entries.extend(folders)

    for folder in folder_entries:
        uri_or_path: str | None = None
        if isinstance(folder, str):
            uri_or_path = folder
        elif isinstance(folder, dict):
            raw_path = folder.get("path")
            raw_uri = folder.get("uri")
            if isinstance(raw_path, str) and raw_path.strip():
                uri_or_path = raw_path
            elif isinstance(raw_uri, str) and raw_uri.strip():
                uri_or_path = raw_uri
        if not uri_or_path:
            continue
        n = _normalize_folder_uri(uri_or_path)
        if n:
            out.append(n)
    return out


def find_workspace_state_dbs_for_path(workspace_root: Path) -> list[Path]:
    """
    Return ``state.vscdb`` paths whose ``workspace.json`` lists ``workspace_root``.

    Scans the editor's workspaceStorage directory (best-effort, order undefined).
    """
    root = Path(os.path.realpath(os.path.normcase(str(workspace_root.resolve()))))
    storage = _workspace_storage_root()
    if not storage.is_dir():
        return []
    found: list[Path] = []
    for child in storage.iterdir():
        if not child.is_dir():
            continue
        wj = child / "workspace.json"
        for p in _read_workspace_json_folders(wj):
            if Path(os.path.realpath(os.path.normcase(p))) == root:
                db = child / "state.vscdb"
                if db.is_file():
                    found.append(db)
                break
    return found


def _query_item_value_from_conn(conn: sqlite3.Connection, key: str) -> str:
    """Read one ItemTable value using an already-open SQLite connection."""
    cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key = ? LIMIT 1", (key,))
    row = cur.fetchone()
    if not row or row[0] is None:
        return ""
    v = row[0]
    if isinstance(v, memoryview):
        v = v.tobytes()
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _parse_ts(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, (int, float)) and 1e9 < val < 1e13:
        return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
    if isinstance(val, (int, float)) and 1e9 < val < 1e12:
        return datetime.fromtimestamp(val, tz=timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        m = re.search(r"(\d{4}-\d{2}-\d{2}T[\d:.\-\+]+)", s)
        if m:
            try:
                t = m.group(1)
                if t.endswith("Z"):
                    t = t[:-1] + "+00:00"
                return datetime.fromisoformat(t)
            except ValueError:
                pass
    return None


def _normalize_role(t: str) -> str:
    t = t.lower()
    if t in ("user", "human"):
        return "user"
    if t in ("ai", "assistant", "model", "bot"):
        return "assistant"
    return t


def _bubbles_from_tab(tab: dict[str, Any]) -> Iterator[tuple[datetime | None, str, str]]:
    ts = _parse_ts(tab.get("timestamp") or tab.get("lastMessageDate") or tab.get("lastUpdatedAt"))
    for b in tab.get("bubbles") or []:
        if not isinstance(b, dict):
            continue
        role = _normalize_role(str(b.get("type") or b.get("role") or ""))
        if role not in ("user", "assistant"):
            continue
        text = str(b.get("text") or b.get("content") or b.get("message") or "").strip()
        bts = _parse_ts(
            b.get("timestamp")
            or b.get("createdAt")
            or b.get("date")
        ) or ts
        if not text:
            continue
        code_blocks = b.get("codeBlocks") or []
        if isinstance(code_blocks, list) and code_blocks:
            for cb in code_blocks:
                if isinstance(cb, dict) and cb.get("code"):
                    text += f"\n```{cb.get('language', '')}\n{cb.get('code', '')}\n```"
        yield bts, role, text


def _load_tabs_from_value(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    tabs: list[dict[str, Any]] = []
    if isinstance(data, dict) and "tabs" in data:
        tabs.extend([t for t in data.get("tabs", []) if isinstance(t, dict)])
    elif isinstance(data, list):
        tabs.extend([t for t in data if isinstance(t, dict)])
    if isinstance(data, dict) and "bubbles" in data and "tabs" not in data:
        tabs.append(data)
    return tabs


def _walk_composer_json(obj: Any) -> list[dict[str, Any]]:
    """Best-effort collect tab-like dicts from composer.composerData shapes."""
    if isinstance(obj, dict):
        if "bubbles" in obj and "tabs" not in obj:
            return [obj]
        for k in ("tabs", "chats", "conversations", "allComposers", "composers"):
            v = obj.get(k)
            if isinstance(v, list) and v:
                out: list[dict[str, Any]] = []
                for it in v:
                    if isinstance(it, dict) and (it.get("bubbles") or it.get("messages")):
                        if "bubbles" not in it and isinstance(it.get("messages"), list):
                            bubs = []
                            for m in it["messages"]:
                                if isinstance(m, dict):
                                    role = m.get("type") or m.get("role")
                                    body = m.get("text") or m.get("content", "")
                                    bubs.append({"type": role, "text": body})
                            it = {**it, "bubbles": bubs}
                        out.append(it)
                if out:
                    return out
    return []


def _parse_chatdata(raw: str) -> list[ChatTurn]:
    turns: list[ChatTurn] = []
    for tab in _load_tabs_from_value(raw):
        for bts, role, text in _bubbles_from_tab(tab):
            turns.append(ChatTurn(bts, role, text))
    return turns


def _parse_composerdata(raw: str) -> list[ChatTurn]:
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    all_tabs: list[dict[str, Any]] = _walk_composer_json(data) or _load_tabs_from_value(raw)
    turns: list[ChatTurn] = []
    for tab in all_tabs:
        for bts, role, text in _bubbles_from_tab(tab):
            turns.append(ChatTurn(bts, role, text))
    return turns


def _merge_turns(a: list[ChatTurn], b: list[ChatTurn]) -> list[ChatTurn]:
    if not a:
        return b
    if not b:
        return a
    def key(t: ChatTurn) -> tuple:
        t0 = t.ts.timestamp() if t.ts else 0.0
        return (t0, t.role, hash(t.text[:120]))
    merged = {key(t): t for t in a}
    for t in b:
        merged[key(t)] = t
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return sorted(merged.values(), key=lambda x: (x.ts or epoch))


def read_cursor_chat_for_workspace(
    workspace_root: Path,
) -> str:
    """
    Load extracted human chat text from the workspace's Cursor ``state.vscdb`` (if any).

    Args:
        workspace_root: Git / project root to match in workspaceStorage.

    Returns:
        Chronologically ordered text payload joined by ``\n\n---\n\n``.
    """
    dbs = find_workspace_state_dbs_for_path(workspace_root)
    if not dbs:
        sys.stderr.write(
            f"[CEREBRO DEBUG] No Cursor workspace matched path: "
            f"{os.path.realpath(str(workspace_root.resolve()))}\n"
        )
        sys.stderr.flush()
    extracted_turns: list[tuple[int, str]] = []
    found_chat_rows = False
    for db in dbs:
        temp_db_path = tempfile.mktemp(suffix=".sqlite")
        conn: sqlite3.Connection | None = None
        try:
            shutil.copy2(db, temp_db_path)
            conn = sqlite3.connect(temp_db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM ItemTable "
                "WHERE key = 'aiService.generations' OR key LIKE '%chat%' OR key LIKE '%composer%'"
            )
            rows = cur.fetchall()
            if rows:
                found_chat_rows = True
            for row in rows:
                if not row or row[0] is None:
                    continue
                raw_value = row[0]
                if isinstance(raw_value, memoryview):
                    raw_value = raw_value.tobytes()
                if isinstance(raw_value, bytes):
                    raw = raw_value.decode("utf-8", errors="replace")
                else:
                    raw = str(raw_value)
                try:
                    parsed = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(parsed, list):
                    continue
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("textDescription") or item.get("text") or item.get("prompt")
                    ts = item.get("unixMs", 0)
                    if not text:
                        continue
                    try:
                        ts_i = int(ts)
                    except (TypeError, ValueError):
                        ts_i = 0
                    extracted_turns.append((ts_i, str(text).strip()))
        except (OSError, sqlite3.Error):
            continue
        finally:
            if conn is not None:
                conn.close()
            try:
                os.remove(temp_db_path)
            except OSError:
                pass

    if dbs and not found_chat_rows:
        sys.stderr.write("[CEREBRO DEBUG] Found workspace DB but no chat data.\n")
        sys.stderr.flush()
    extracted_turns.sort(key=lambda x: x[0])
    payload_chunks = [text for _, text in extracted_turns if text]
    return "\n\n---\n\n".join(payload_chunks)


def format_chat_for_compiler(turns: list[ChatTurn]) -> str:
    """Dense plain-text block for the compiler prompt."""
    if not turns:
        return ""
    lines: list[str] = []
    for t in turns:
        r = t.role
        if r == "assistant":
            r = "assistant"
        ts = ""
        if t.ts:
            t0 = t.ts if t.ts.tzinfo else t.ts.replace(tzinfo=timezone.utc)
            ts = t0.astimezone(timezone.utc).isoformat() + " "
        text = t.text.replace("\r\n", "\n").strip()
        if not text:
            continue
        lines.append(f"[{ts}{r}]\n{text}")
    return "\n\n---\n\n".join(lines)


def read_unpushed_patch_text(repo_root: Path) -> str:
    """
    Raw patches for commits not in the upstream tracking branch (``git log UP..HEAD -p``).

    Tries ``@{u}``, then ``origin/main``, then ``origin/master``. Empty if none apply.
    """
    root = repo_root.resolve()
    upstreams: list[str] = []
    try:
        p = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if p.returncode == 0 and p.stdout.strip():
            upstreams.append(p.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    for u in ("origin/main", "origin/master"):
        if u not in upstreams:
            upstreams.append(u)
    for up in upstreams:
        try:
            chk = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--verify", up],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if chk.returncode != 0:
                continue
            diff = subprocess.run(
                ["git", "-C", str(root), "log", f"{up}..HEAD", "-p", "--no-color"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if diff.returncode != 0:
                continue
            return (diff.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            continue
    return ""


