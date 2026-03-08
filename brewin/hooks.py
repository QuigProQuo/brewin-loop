"""
Hook system for Brewin Loop.
Runs shell commands before/after cycles and sessions.
"""

import os
import signal
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
        proc = None
        try:
            # Run in a new process group so we can kill the entire tree on timeout
            proc = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=cwd, env=env,
                start_new_session=True,
            )
            stdout, stderr = proc.communicate(timeout=HOOK_TIMEOUT)
            if proc.returncode != 0:
                console.print(
                    f"  [yellow]Hook ({label}) failed: {cmd}[/yellow]\n"
                    f"    {stderr.strip()[:200]}"
                )
            else:
                console.print(f"  [dim]Hook ({label}): {cmd} — ok[/dim]")
        except subprocess.TimeoutExpired:
            # Kill the entire process group, not just the shell
            if proc:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except OSError:
                    proc.kill()
                proc.wait(timeout=5)
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
