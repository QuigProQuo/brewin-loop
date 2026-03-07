"""
Runs `claude -p` as a subprocess. Uses your Claude Code Max subscription.
"""

import os
import shutil
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()

CLAUDE_TIMEOUT = 900  # 15 minutes max per cycle


def _find_claude_cli() -> str:
    path = shutil.which("claude")
    if path:
        return path
    candidates = [
        os.path.expanduser("~/.claude/local/claude"),
        os.path.expanduser("~/.local/bin/claude"),
        "/usr/local/bin/claude",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError("claude CLI not found")


def run_cycle(user_message: str, system_prompt: str,
              model: str | None = None, cwd: str | None = None) -> str:
    """Run a single Brewin cycle via claude -p."""
    claude_bin = _find_claude_cli()

    cmd = [
        claude_bin,
        "-p",
        "--output-format", "text",
        "--dangerously-skip-permissions",
    ]

    if model:
        cmd.extend(["--model", model])

    if system_prompt.strip():
        cmd.extend(["--system-prompt", system_prompt])

    cmd.append(user_message)

    console.print(f"  [dim]Running claude -p ({model or 'default'})...[/dim]")

    # Strip all Claude env vars to allow launching from within a Claude session
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            cwd=cwd or os.getcwd(),
            env=env,
        )

        output = result.stdout.strip()
        if result.stderr and not output:
            output = result.stderr.strip()

        if result.returncode != 0 and not output:
            return f"(Claude CLI exited with code {result.returncode})\n{result.stderr}"

        # Show preview
        lines = output.splitlines()
        preview = "\n".join(lines[:15])
        if len(lines) > 15:
            preview += f"\n... ({len(lines)} total lines)"
        console.print(Panel(
            Markdown(preview[:3000]),
            title="Claude Output",
            border_style="blue",
            expand=False,
        ))

        return output

    except subprocess.TimeoutExpired:
        console.print("[red]Claude CLI timed out.[/red]")
        return "(Cycle stopped — timed out)"
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return f"(Cycle stopped — error: {e})"
