"""
Hook system for Brewin Loop.
Runs shell commands before/after cycles and sessions.
"""

import os
import subprocess

from rich.console import Console

console = Console()

HOOK_TIMEOUT = 30  # seconds


def run_hooks(
    hooks: list[str],
    label: str,
    env_extras: dict[str, str] | None = None,
    cwd: str | None = None,
):
    """Run a list of shell commands as hooks. Non-blocking on failure."""
    if not hooks:
        return

    env = os.environ.copy()
    if env_extras:
        env.update(env_extras)

    for cmd in hooks:
        try:
            result = subprocess.run(
                cmd, shell=True,
                capture_output=True, text=True,
                timeout=HOOK_TIMEOUT,
                cwd=cwd, env=env,
            )
            if result.returncode != 0:
                console.print(
                    f"  [yellow]Hook ({label}) failed: {cmd}[/yellow]\n"
                    f"    {result.stderr.strip()[:200]}"
                )
            else:
                console.print(f"  [dim]Hook ({label}): {cmd} — ok[/dim]")
        except subprocess.TimeoutExpired:
            console.print(f"  [yellow]Hook ({label}) timed out: {cmd}[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]Hook ({label}) error: {e}[/yellow]")


def build_hook_env(
    cycle: int = 0,
    outcome: str = "",
    focus: str = "",
    session_id: str = "",
    time_remaining: str = "",
) -> dict[str, str]:
    """Build environment variables for hook commands."""
    return {
        "BREWIN_CYCLE": str(cycle),
        "BREWIN_OUTCOME": outcome,
        "BREWIN_FOCUS": focus,
        "BREWIN_SESSION_ID": session_id,
        "BREWIN_TIME_REMAINING": time_remaining,
    }
