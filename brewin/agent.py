"""
Runs `claude -p` as a subprocess with streaming output.
Uses your Claude Code Max subscription.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel

console = Console()

STALL_TIMEOUT = 300  # 5 minutes with no output = stalled


@dataclass
class CycleResult:
    output: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    session_id: str = ""
    is_error: bool = False
    num_turns: int = 0
    timeout_type: str = ""  # "", "stall", or "duration"
    partial_diff_stat: str = ""
    partial_diff: str = ""


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


def _save_partial_work(work_dir: str) -> tuple[str, str] | None:
    """Auto-commit uncommitted changes as a WIP save.
    Returns (diff_stat, diff) if there were changes, None otherwise."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=work_dir, timeout=10,
        )
        if not status.stdout.strip():
            return None

        # Stage everything first so we capture new untracked files in the diff
        subprocess.run(
            ["git", "add", "-A"], cwd=work_dir, timeout=10,
        )

        diff_stat = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            capture_output=True, text=True, cwd=work_dir, timeout=10,
        )
        diff_detail = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True, text=True, cwd=work_dir, timeout=10,
        )

        subprocess.run(
            ["git", "commit", "-m",
             "brewin: WIP auto-save (cycle stalled)"],
            cwd=work_dir, timeout=10,
        )

        console.print("  [yellow]Partial work auto-saved as WIP commit[/yellow]")
        return (diff_stat.stdout.strip(), diff_detail.stdout.strip())
    except Exception as e:
        console.print(f"  [dim red]Failed to save partial work: {e}[/dim red]")
        return None


def run_cycle(
    user_message: str,
    system_prompt: str | None = None,
    model: str | None = None,
    cwd: str | None = None,
    session_id: str | None = None,
    continue_session: bool = False,
    timeout: int | None = None,
) -> CycleResult:
    """Run a single Brewin cycle via claude -p with streaming output."""
    claude_bin = _find_claude_cli()
    start_time = time.time()

    cmd = [
        claude_bin,
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]

    if model:
        cmd.extend(["--model", model])

    if system_prompt and system_prompt.strip():
        cmd.extend(["--system-prompt", system_prompt])

    if session_id and continue_session:
        cmd.extend(["--session-id", session_id])

    cmd.append(user_message)

    console.print(f"  [dim]Running claude -p ({model or 'default'})...[/dim]")

    # Strip all Claude env vars to allow launching from within a Claude session
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}

    result = CycleResult()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd or os.getcwd(),
            env=env,
        )

        output_chunks: list[str] = []
        last_output_time = time.time()
        # Stall timeout is always STALL_TIMEOUT (no output for N seconds).
        # The cycle type timeout is the max overall duration — enforced separately.
        stall_limit = STALL_TIMEOUT
        max_duration = timeout  # None means no hard cap

        # Watchdog thread for stall detection and optional max duration
        stalled = threading.Event()
        was_killed = threading.Event()
        timeout_reason = ""  # "stall" or "duration"
        saved_diff: tuple[str, str] | None = None

        def _kill_proc(reason: str, kill_type: str = "stall"):
            """Terminate process, save partial work, escalate to SIGKILL."""
            nonlocal timeout_reason, saved_diff
            timeout_reason = kill_type
            was_killed.set()
            stalled.set()

            # Stop Claude first
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

            # Save any uncommitted work before it's lost
            saved_diff = _save_partial_work(cwd or os.getcwd())

            # Ensure process is dead
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

            console.print(f"\n[red]{reason}[/red]")

        def watchdog():
            while proc.poll() is None and not stalled.is_set():
                now = time.time()
                stall_elapsed = now - last_output_time
                total_elapsed = now - start_time

                # Check optional max duration first
                if max_duration and total_elapsed > max_duration:
                    _kill_proc(
                        f"Cycle duration limit reached ({max_duration}s). "
                        "Terminating.",
                        kill_type="duration",
                    )
                    return

                if stall_elapsed > stall_limit:
                    _kill_proc(
                        f"Stall detected ({stall_limit}s with no output). "
                        "Terminating cycle.",
                        kill_type="stall",
                    )
                    return
                time.sleep(5)

        watcher = threading.Thread(target=watchdog, daemon=True)
        watcher.start()

        # Stream stdout line-by-line
        for line in proc.stdout:
            last_output_time = time.time()
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            _handle_stream_event(event, output_chunks, result)

        proc.wait()
        stalled.set()  # Stop watchdog

        result.output = "".join(output_chunks)
        result.duration_seconds = time.time() - start_time

        # Mark as error if process was killed by watchdog
        if was_killed.is_set():
            result.is_error = True
            result.timeout_type = timeout_reason
            if saved_diff:
                result.partial_diff_stat = saved_diff[0]
                result.partial_diff = saved_diff[1][:3000]
            if not result.output:
                result.output = "(Cycle terminated by watchdog)"

        # Mark as error if process exited with non-zero
        if proc.returncode != 0 and not result.is_error:
            result.is_error = True
            if not result.output:
                stderr = proc.stderr.read() if proc.stderr else ""
                result.output = f"(Claude CLI exited with code {proc.returncode})\n{stderr}"

        # Show summary
        lines = result.output.splitlines()
        preview = "\n".join(lines[:10])
        if len(lines) > 10:
            preview += f"\n... ({len(lines)} total lines)"
        console.print(Panel(
            preview[:3000],
            title="Cycle Output Summary",
            border_style="blue",
            expand=False,
        ))

        return result

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return CycleResult(
            output=f"(Cycle stopped — error: {e})",
            is_error=True,
            duration_seconds=time.time() - start_time,
        )


def _handle_stream_event(
    event: dict, output_chunks: list[str], result: CycleResult
):
    """Process a single stream-json event from Claude CLI."""
    event_type = event.get("type")

    if event_type == "assistant":
        # Assistant message with content blocks
        message = event.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "")
                output_chunks.append(text)
            elif block.get("type") == "tool_use":
                tool_name = block.get("name", "unknown")
                console.print(f"  [dim cyan]tool: {tool_name}[/dim cyan]")

    elif event_type == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            output_chunks.append(text)

    elif event_type == "result":
        # Final result with metadata
        result.session_id = event.get("session_id", result.session_id)
        result.num_turns = event.get("num_turns", 0)
        result.cost_usd = event.get("cost_usd", 0.0)
        result.duration_seconds = event.get("duration_ms", 0) / 1000.0

        usage = event.get("usage", {})
        result.input_tokens = usage.get("input_tokens", 0)
        result.output_tokens = usage.get("output_tokens", 0)

        # Also check for result text
        result_text = event.get("result", "")
        if result_text and not output_chunks:
            output_chunks.append(result_text)

    elif event_type == "system":
        # System messages (session info, etc.)
        session_id = event.get("session_id", "")
        if session_id:
            result.session_id = session_id
