"""
Git checkpoint system for Brewin Loop.
Creates tags before each cycle so broken cycles can be rolled back.
"""

import subprocess
from dataclasses import dataclass

from rich.console import Console

console = Console()


@dataclass
class CheckpointResult:
    tag: str
    success: bool
    had_uncommitted: bool = False
    error: str = ""


def _git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True, text=True,
        cwd=cwd, timeout=30,
    )


def _has_uncommitted_changes(cwd: str | None = None) -> bool:
    result = _git("status", "--porcelain", cwd=cwd)
    return bool(result.stdout.strip())


def create_checkpoint(cycle: int, session_id: str,
                      cwd: str | None = None) -> CheckpointResult:
    """Create a git tag before a cycle. Auto-commits uncommitted work."""
    tag = f"brewin/{session_id}/pre-cycle-{cycle}"
    had_uncommitted = False

    try:
        # Commit any uncommitted work first
        if _has_uncommitted_changes(cwd):
            had_uncommitted = True
            _git("add", "-A", cwd=cwd)
            _git("commit", "-m", f"brewin: auto-checkpoint before cycle {cycle}",
                 "--no-verify", cwd=cwd)

        # Create tag
        result = _git("tag", tag, cwd=cwd)
        if result.returncode != 0:
            return CheckpointResult(
                tag=tag, success=False,
                error=result.stderr.strip(),
                had_uncommitted=had_uncommitted,
            )

        console.print(f"  [dim]Checkpoint: {tag}[/dim]")
        return CheckpointResult(
            tag=tag, success=True,
            had_uncommitted=had_uncommitted,
        )

    except Exception as e:
        return CheckpointResult(tag=tag, success=False, error=str(e))


def rollback_to_checkpoint(tag: str, cwd: str | None = None) -> bool:
    """Roll back to a checkpoint tag via git reset --hard."""
    try:
        result = _git("reset", "--hard", tag, cwd=cwd)
        if result.returncode == 0:
            console.print(f"  [yellow]Rolled back to {tag}[/yellow]")
            return True
        console.print(f"  [red]Rollback failed: {result.stderr.strip()}[/red]")
        return False
    except Exception as e:
        console.print(f"  [red]Rollback error: {e}[/red]")
        return False


def list_checkpoints(session_id: str, cwd: str | None = None) -> list[str]:
    """List all checkpoint tags for a session."""
    result = _git("tag", "-l", f"brewin/{session_id}/*", cwd=cwd)
    if result.returncode != 0:
        return []
    return [t.strip() for t in result.stdout.splitlines() if t.strip()]


def cleanup_checkpoints(session_id: str, cwd: str | None = None):
    """Remove all checkpoint tags for a completed session."""
    tags = list_checkpoints(session_id, cwd)
    for tag in tags:
        _git("tag", "-d", tag, cwd=cwd)
    if tags:
        console.print(f"  [dim]Cleaned up {len(tags)} checkpoint tags[/dim]")
