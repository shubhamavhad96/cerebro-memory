"""
Command-line and Git-hook surface for Cerebro.

Coordinates IDE rule injection, pre-push compile hooks, SQLite enqueue (``log``),
and optional GitHub Gist export/import. Transport code for Gists lives in
``cerebro.sync.gist_sync`` to keep this module focused on orchestration.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import traceback
from pathlib import Path
from urllib import error, request

import click

from cerebro.adapters.terminal_wrapper import intercept_and_run
from cerebro.core.compiler import WikiCompiler
from cerebro.storage.sqlite_db import SqliteHippocampus, default_db_path, resolve_repo_root
from cerebro.sync.gist_sync import GITHUB_GISTS_API, fetch_gist_markdown


CEREBRO_MEMORY_PROTOCOL = """=== CEREBRO AI MEMORY PROTOCOL (3.0) ===
1. READ: Before large changes, read `.cerebro/KNOWLEDGE_GRAPH.md` for architectural intent and invariants.
2. CONTEXT: Cerebro autonomously fuses this IDE's chat history with unpushed git diffs and refreshes the wiki on `git push`. Do not maintain separate shadow logs.
=================================="""

_MEMORY_PROTOCOL_MARKER = "=== CEREBRO AI MEMORY PROTOCOL ==="

# Legacy text from pre-3.0 `init` (stripped on upgrade).
_OLD_CEREBRO_PROTOCOL = (
    "CEREBRO PROTOCOL: You are paired with the Cerebro Knowledge system. Throughout our chat, "
    "act as a silent scribe. Whenever we complete a feature, debug an issue, or make a decision, "
    "immediately APPEND a detailed summary of our conversation and your reasoning to "
    "`.cerebro/shadow_log.md` without asking."
)

# Commits ``KNOWLEDGE_GRAPH.md``; other ``.cerebro/`` artifacts stay private.
CEREBRO_GITIGNORE_BLOCK = """# ========================
# Cerebro AI Memory System
# ========================
.cerebro/*
!.cerebro/KNOWLEDGE_GRAPH.md
"""

_GITHUB_USER_AGENT = "Cerebro-Memory/1.0 (urllib; local export/import)"


def _inject_memory_protocol(target: Path) -> None:
    """
    Merge the READ/WRITE memory protocol into an IDE rules file (idempotent).

    Skips if the current protocol marker is present; strips legacy one-line
    protocol text when upgrading.

    Args:
        target: Path to ``.cursorrules`` or ``CLAUDE.md`` (created if missing).
    """
    if target.is_file():
        try:
            body = target.read_text(encoding="utf-8")
        except OSError:
            body = ""
        if _MEMORY_PROTOCOL_MARKER in body:
            return
        cleaned = body.replace(_OLD_CEREBRO_PROTOCOL, "").rstrip()
        suffix = "\n\n" if cleaned else ""
        target.write_text(f"{cleaned}{suffix}{CEREBRO_MEMORY_PROTOCOL}\n", encoding="utf-8")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(CEREBRO_MEMORY_PROTOCOL + "\n", encoding="utf-8")


def _ensure_gitignore_cerebro_block(root: Path) -> None:
    """
    Ensure ``.gitignore`` ignores ``.cerebro/*`` while allowing ``KNOWLEDGE_GRAPH.md``.

    Upgrades legacy ``.cerebro/``-only rules from Cerebro 2.x in place when present.
    """
    gi = root / ".gitignore"
    marker = "# Cerebro AI Memory System"
    unignore = "!.cerebro/KNOWLEDGE_GRAPH.md"
    try:
        text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    except OSError:
        text = ""
    if marker in text and unignore in text:
        return
    if marker in text and unignore not in text:
        text = text.replace(".cerebro/\n", ".cerebro/*\n" + unignore + "\n", 1)
        if unignore not in text:
            text = text.replace(
                "# ========================\n# Cerebro AI Memory System\n# ========================\n.cerebro/\n",
                CEREBRO_GITIGNORE_BLOCK,
                1,
            )
        try:
            gi.write_text(text, encoding="utf-8")
        except OSError:
            pass
        return
    if gi.is_file():
        with gi.open("a", encoding="utf-8") as fh:
            fh.write("\n" + CEREBRO_GITIGNORE_BLOCK)
    else:
        gi.write_text(CEREBRO_GITIGNORE_BLOCK, encoding="utf-8")


def _git_dir(repo: Path) -> Path | None:
    """
    Resolve the ``.git`` directory for ``repo`` via ``git rev-parse --git-dir``.

    Args:
        repo: Working tree path.

    Returns:
        Path | None: Absolute ``.git`` path, or None if not a git repo.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    raw = (proc.stdout or "").strip().splitlines()
    if not raw:
        return None
    gd = Path(raw[0]).expanduser()
    if not gd.is_absolute():
        gd = (repo / gd).resolve()
    return gd.resolve()


def _write_pre_push_hook(hook_path: Path) -> None:
    """
    Write an executable ``pre-push`` hook: run ``cerebro compile`` (fail-soft), commit wiki.

    Uses the interpreter running the installer so venv-bound installs stay consistent.
    If the LLM is offline, the hook prints a warning and returns success so the push continues.
    """
    exe = sys.executable.replace('"', '\\"')
    body = """#!/usr/bin/env bash
set -eu
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || exit 0
export CEREBRO_PRE_PUSH=1
export CEREBRO_COMPILE_QUIET=1
PYTHON="__PYTHON_EXE__"
set +e
OUT=$("$PYTHON" -m cerebro.interface.cli compile --quiet 2>&1)
RC=$?
set -e
if [[ $RC -ne 0 ]]; then
  echo "[Cerebro] compile exited with status $RC; your push will continue. $OUT" >&2
  exit 0
fi
STAT=$(git status --porcelain -- .cerebro/KNOWLEDGE_GRAPH.md 2>/dev/null | head -1 || true)
if [[ -n "${STAT}" ]]; then
  # Note: This commit will sync to remote on the NEXT push due to Git's pre-push lifecycle.
  git add .cerebro/KNOWLEDGE_GRAPH.md
  git commit --no-verify -m "chore(cerebro): sync OS-level memory" || true
fi
exit 0
""".replace(
        "__PYTHON_EXE__", exe
    )
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(body, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@click.group(help="Cerebro: OS-level LLM-wiki compiler (unpushed diffs + IDE chat).")
def main() -> None:
    """Root Click group; subcommands map to hook and operator workflows."""
    pass


@main.command("init", help="Install Cerebro protocol, .gitignore block, and pre-push hook.")
def init_cmd() -> None:
    """
    One-time project wiring: IDE directives, ``.cerebro/`` (except ignored artifacts), pre-push.

    Appends the memory protocol, ensures ``.gitignore`` allows ``KNOWLEDGE_GRAPH.md``,
    and writes ``pre-push`` when inside a git work tree.
    """
    workflow = click.prompt(
        "Where do you write code? [1] Desktop IDE (Cursor, Windsurf), [2] Terminal CLI (Claude Code)",
        type=click.Choice(["1", "2"]),
        default="1",
        show_default=False,
        show_choices=False,
    )

    root = resolve_repo_root()
    _inject_memory_protocol(root / ".cursorrules")
    _inject_memory_protocol(root / "CLAUDE.md")
    _ensure_gitignore_cerebro_block(root)
    cerebro_dir = root / ".cerebro"
    cerebro_dir.mkdir(parents=True, exist_ok=True)

    gd = _git_dir(root)
    if gd is None:
        click.secho(
            "[ERROR] Not a git repository (or git unavailable); hook not installed.",
            fg="red",
            err=True,
        )
        return
    hook = gd / "hooks" / "pre-push"
    _write_pre_push_hook(hook)
    mcp_script = str(root / "src" / "cerebro" / "adapters" / "mcp_server.py")
    mcp_payload = {"command": sys.executable, "args": [mcp_script]}

    if workflow == "1":
        ide = click.prompt(
            "Which IDE are you using? [1] Cursor, [2] Windsurf",
            type=click.Choice(["1", "2"]),
            default="1",
            show_default=False,
            show_choices=False,
        )
        if ide == "1":
            cursor_dir = root / ".cursor"
            cursor_dir.mkdir(parents=True, exist_ok=True)
            cursor_cfg = cursor_dir / "mcp.json"
            data: dict[str, object]
            if cursor_cfg.is_file():
                try:
                    with cursor_cfg.open("r", encoding="utf-8") as f:
                        parsed = json.load(f)
                    data = parsed if isinstance(parsed, dict) else {"mcpServers": {}}
                except (OSError, json.JSONDecodeError):
                    data = {"mcpServers": {}}
            else:
                data = {"mcpServers": {}}
            servers = data.get("mcpServers")
            if not isinstance(servers, dict):
                servers = {}
                data["mcpServers"] = servers
            servers["Cerebro"] = mcp_payload
            with cursor_cfg.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            click.secho(
                "[SUCCESS] Cursor MCP server automatically configured in .cursor/mcp.json.",
                fg="green",
                bold=True,
            )
            click.secho(
                "Hint: Open Cursor Settings (Cmd+Shift+J) > Tools & MCPs. Find 'Cerebro' in the list and ensure it is toggled ON.",
                fg="yellow",
            )
        if ide == "2":
            windsurf_dir = Path.home() / ".codeium" / "windsurf"
            windsurf_dir.mkdir(parents=True, exist_ok=True)
            windsurf_cfg = windsurf_dir / "mcp_config.json"
            data: dict[str, object]
            if windsurf_cfg.is_file():
                try:
                    with windsurf_cfg.open("r", encoding="utf-8") as f:
                        parsed = json.load(f)
                    data = parsed if isinstance(parsed, dict) else {"mcpServers": {}}
                except (OSError, json.JSONDecodeError):
                    data = {"mcpServers": {}}
            else:
                data = {"mcpServers": {}}
            servers = data.get("mcpServers")
            if not isinstance(servers, dict):
                servers = {}
                data["mcpServers"] = servers
            servers["Cerebro"] = mcp_payload
            with windsurf_cfg.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            click.secho(
                "[SUCCESS] Windsurf MCP server automatically configured.",
                fg="green",
                bold=True,
            )
    if workflow == "2":
        click.secho(
            "[ACTION REQUIRED] Terminal Proxy Setup",
            fg="yellow",
            bold=True,
        )
        click.secho(
            "To make Cerebro invisible, it needs to intercept your AI CLI commands.",
            fg="white",
        )
        click.secho(
            "Run this exact command once in your terminal to create the alias:",
            fg="white",
        )
        click.secho(
            "echo 'alias claude=\"cerebro run claude\"' >> ~/.zshrc && source ~/.zshrc",
            fg="cyan",
            bold=True,
        )

    click.echo("")  # blank line for spacing
    click.secho("[SUCCESS] Cerebro initialized.", fg="green", bold=True)

    # Print Knowledge Base Path
    click.secho("  • Knowledge Base : ", fg="white", bold=True, nl=False)
    click.secho(str(cerebro_dir), fg="cyan")

    # Print Git Hook Path
    click.secho("  • Auto-Compiler  : ", fg="white", bold=True, nl=False)
    click.secho(str(hook), fg="cyan")
    click.echo("")  # blank line for spacing


@main.command("log", help="Append a raw event to the hippocampus (SQLite).")
@click.argument("message", nargs=-1, required=True)
def log_cmd(message: tuple[str, ...]) -> None:
    """
    Persist one opaque event string (hook or operator) into the SQLite queue.

    Args:
        message: Tokenized argv joined with spaces; must be non-empty after strip.
    """
    msg = " ".join(message).strip()
    root = resolve_repo_root()
    hippo = SqliteHippocampus(db_path=default_db_path(root))
    event_id = hippo.log_event(msg)
    click.secho(f"logged event_id={event_id} ", fg="green", nl=False)
    click.secho(f"db={hippo.db_path}", fg="cyan")


@main.command("compile", help="Fuse unpushed diffs + Cursor chat into .cerebro/KNOWLEDGE_GRAPH.md.")
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress success/noop messages (for hooks; still shows warnings in hook mode).",
)
def compile_cmd(quiet: bool) -> None:
    """
    Run ``WikiCompiler`` with local git + IDE payload. In ``CEREBRO_PRE_PUSH=1`` mode, always
    exits 0 and prints a warning if no LLM is available, so the push is not blocked.
    """
    if quiet:
        os.environ["CEREBRO_COMPILE_QUIET"] = "1"
    root = resolve_repo_root()
    hook_mode = bool(os.environ.get("CEREBRO_PRE_PUSH", "").strip())
    compiler = WikiCompiler(out_dir=root / ".cerebro")
    try:
        result = compiler.compile()
    except Exception as exc:
        if hook_mode:
            click.secho(
                f"[Cerebro] compile failed; push will continue: {exc}",
                fg="yellow",
                err=True,
            )
            raise SystemExit(0)
        click.secho(f"[ERROR] compile failed: {exc}", fg="red", err=True)
        raise SystemExit(1) from exc

    status = str(result.get("status", ""))
    if status == "llm_unavailable" and hook_mode:
        click.secho(
            "[Cerebro] No LLM available (Ollama/API); skipping wiki update. Push continues.",
            fg="yellow",
            err=True,
        )
        raise SystemExit(0)
    if status == "llm_unavailable" and not hook_mode:
        click.secho(
            "[Cerebro] No LLM available (Ollama/API); KNOWLEDGE_GRAPH.md not updated.",
            fg="yellow",
            err=True,
        )
        return
    if status == "error" and hook_mode:
        click.secho(
            "[Cerebro] Compiler error; push continues without updating KNOWLEDGE_GRAPH.md.",
            fg="yellow",
            err=True,
        )
        raise SystemExit(0)
    if status == "error":
        raise SystemExit(1)

    if not quiet:
        if status == "noop":
            click.secho(
                "No new memories to compile (no unpushed diffs and no Cursor chat).",
                fg="yellow",
            )
        elif status == "ok":
            wiki_file = str(result.get("file", ""))
            d = "yes" if result.get("has_diffs") else "no"
            c = "yes" if result.get("has_chat") else "no"
            click.secho("compiled file=", fg="green", nl=False)
            click.secho(wiki_file, fg="cyan", nl=False)
            click.secho(f" (diffs={d}, chat={c})", fg="green")


@main.command("share", help="Upload .cerebro/KNOWLEDGE_GRAPH.md as a secret GitHub Gist.")
def share_cmd() -> None:
    """
    POST the current graph to ``GITHUB_GISTS_API`` as a secret gist.

    Requires ``GITHUB_TOKEN`` or ``GH_TOKEN`` with ``gist`` scope for reliable auth.
    """
    root = resolve_repo_root()
    wiki = root / ".cerebro" / "KNOWLEDGE_GRAPH.md"
    if not wiki.is_file():
        click.secho(
            "[ERROR] KNOWLEDGE_GRAPH.md not found. Run `cerebro compile` first.",
            fg="red",
            err=True,
        )
        raise SystemExit(1)
    try:
        content = wiki.read_text(encoding="utf-8")
    except OSError as exc:
        click.secho(f"[ERROR] Could not read wiki file: {exc}", fg="red", err=True)
        raise SystemExit(1) from exc

    payload = {
        "description": "Cerebro Team Brain",
        "public": False,
        "files": {"KNOWLEDGE_GRAPH.md": {"content": content}},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
        "User-Agent": _GITHUB_USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = request.Request(
            GITHUB_GISTS_API,
            data=body,
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except error.HTTPError as exc:
        hint = ""
        if exc.code in (401, 403):
            hint = " Set GITHUB_TOKEN (classic PAT with gist scope) or GH_TOKEN and retry."
        click.secho(
            f"[ERROR] GitHub API HTTP {exc.code}: {exc.reason}.{hint}",
            fg="red",
            err=True,
        )
        raise SystemExit(1) from exc
    except error.URLError as exc:
        click.secho(f"[ERROR] Network error: {exc.reason}", fg="red", err=True)
        raise SystemExit(1) from exc
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
        click.secho(f"[ERROR] Export failed: {exc}", fg="red", err=True)
        raise SystemExit(1) from exc

    if not isinstance(data, dict):
        click.secho("[ERROR] Unexpected response from GitHub.", fg="red", err=True)
        raise SystemExit(1)

    html_url = str(data.get("html_url") or "").strip()
    if not html_url:
        click.secho("[ERROR] Response missing html_url.", fg="red", err=True)
        raise SystemExit(1)

    click.secho(
        "[SUCCESS] Brain exported. Share this link with your team: ",
        fg="green",
        nl=False,
    )
    click.secho(html_url, fg="cyan")


@main.command(
    "import_brain",
    help="Download a team Gist and overwrite local .cerebro/KNOWLEDGE_GRAPH.md.",
)
@click.argument("gist_url")
def import_brain_cmd(gist_url: str) -> None:
    """
    Download remote gist content and overwrite ``.cerebro/KNOWLEDGE_GRAPH.md``.

    Args:
        gist_url: HTML or raw gist URL resolvable by ``fetch_gist_markdown``.
    """
    root = resolve_repo_root()
    out_dir = root / ".cerebro"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "KNOWLEDGE_GRAPH.md"
    try:
        text = fetch_gist_markdown(gist_url)
    except error.URLError as exc:
        click.secho(f"[ERROR] Network error: {exc.reason}", fg="red", err=True)
        raise SystemExit(1) from exc
    except error.HTTPError as exc:
        click.secho(
            f"[ERROR] HTTP {exc.code}: {exc.reason}",
            fg="red",
            err=True,
        )
        raise SystemExit(1) from exc
    except (ValueError, RuntimeError, OSError, UnicodeDecodeError) as exc:
        click.secho(f"[ERROR] Import failed: {exc}", fg="red", err=True)
        raise SystemExit(1) from exc

    try:
        dest.write_text(text, encoding="utf-8")
    except OSError as exc:
        click.secho(f"[ERROR] Could not write {dest}: {exc}", fg="red", err=True)
        raise SystemExit(1) from exc

    click.secho(
        "[SUCCESS] Team memory injected at ",
        fg="green",
        nl=False,
    )
    click.secho(str(dest), fg="cyan", nl=False)
    click.secho(". Your local AI is now synced.", fg="green")


@main.command(context_settings={"ignore_unknown_options": True}, hidden=True)
@click.argument("cmd_args", nargs=-1, type=click.UNPROCESSED)
def run(cmd_args: tuple[str, ...]) -> None:
    """Hidden proxy to intercept terminal AI commands."""
    intercept_and_run(cmd_args)


def cli() -> None:
    """
    Entry point for the ``cerebro`` setuptools console script.

    Invokes the Click application group ``main`` (see ``pyproject.toml``).
    """
    try:
        main()
    except Exception as e:
        if os.environ.get("CEREBRO_DEBUG"):
            traceback.print_exc()
        else:
            click.secho(f"[CEREBRO FATAL] {e}", fg="red", err=True)
            click.secho(
                "Hint: Run with CEREBRO_DEBUG=1 to see the full stack trace.",
                fg="yellow",
                err=True,
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
