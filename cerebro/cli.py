"""Command-line entry points for Cerebro developer tooling."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def explore() -> None:
    """Launch the Streamlit observability dashboard (read-only vault UI).

    Spawns ``streamlit run`` against :mod:`cerebro.viz` with the repository
    root as working directory so package imports resolve consistently.

    Args:
        None.

    Returns:
        None.

    Raises:
        None: Subprocess exit codes are not raised; check the child process output.
    """
    repo_root = Path(__file__).resolve().parent.parent
    viz_script = Path(__file__).resolve().parent / "viz.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(viz_script)]
    subprocess.run(cmd, cwd=str(repo_root), check=False)


def main(argv: Optional[List[str]] = None) -> None:
    """Parse CLI arguments and dispatch subcommands.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        None.

    Raises:
        SystemExit: On invalid invocation, per :mod:`argparse` behavior.
    """
    parser = argparse.ArgumentParser(
        prog="cerebro",
        description="Cerebro memory — developer CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_explore = sub.add_parser(
        "explore",
        help="Open the Streamlit observability suite (TensorBoard-style vault audit).",
    )
    p_explore.set_defaults(_handler=explore)

    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if callable(handler):
        handler()


if __name__ == "__main__":
    main()
