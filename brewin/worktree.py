"""
Git worktree management for Brewin agent isolation.

Each agent runs in its own git worktree so multiple agents can work
on the same repo simultaneously without conflicts.
"""

import os
import shutil
import subprocess
from datetime import datetime, timezone

from rich.console import Console

console = Console()


def _git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True, text=True,
        cwd=cwd, timeout=30,
    )


def create_agent_worktree(
    agent_name: str,
    project_root: str,
) -> str:
    """Create a git worktree for an agent run.

    Creates a new branch named `agent/<name>/<timestamp>` and a worktree
    at `<project_root>/.brewin/worktrees/<name>`.

    Returns the absolute path to the worktree directory.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch = f"agent/{agent_name}/{timestamp}"
    worktree_dir = os.path.join(project_root, ".brewin", "worktrees", agent_name)

    # Clean up stale worktree if it exists
    # Use shutil.rmtree instead of `git worktree remove` because the latter
    # times out on large directories (e.g. node_modules symlinks).
    if os.path.isdir(worktree_dir):
        console.print(f"  [dim]Cleaning up stale worktree at {worktree_dir}[/dim]")
        shutil.rmtree(worktree_dir, ignore_errors=True)
        _git("worktree", "prune", cwd=project_root)

    # Create the worktree with a new branch from current HEAD
    result = _git(
        "worktree", "add", "-b", branch, worktree_dir,
        cwd=project_root,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create worktree: {result.stderr.strip()}"
        )

    console.print(
        f"  [green]Worktree created:[/green] {worktree_dir}\n"
        f"  [green]Branch:[/green] {branch}"
    )

    return os.path.abspath(worktree_dir)


def remove_agent_worktree(
    agent_name: str,
    project_root: str,
) -> bool:
    """Remove an agent's worktree (but keep the branch for review)."""
    worktree_dir = os.path.join(project_root, ".brewin", "worktrees", agent_name)

    if not os.path.isdir(worktree_dir):
        return False

    result = _git("worktree", "remove", worktree_dir, cwd=project_root)
    if result.returncode != 0:
        console.print(
            f"  [yellow]Could not remove worktree cleanly: "
            f"{result.stderr.strip()}[/yellow]"
        )
        # Force removal
        _git("worktree", "remove", "--force", worktree_dir, cwd=project_root)

    console.print(f"  [dim]Worktree removed: {worktree_dir}[/dim]")
    return True


def get_agent_branch(
    agent_name: str,
    project_root: str,
) -> str | None:
    """Get the current branch name for an agent's worktree."""
    worktree_dir = os.path.join(project_root, ".brewin", "worktrees", agent_name)

    if not os.path.isdir(worktree_dir):
        return None

    result = _git("branch", "--show-current", cwd=worktree_dir)
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None
