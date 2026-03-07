#!/usr/bin/env python3
"""
Brewin Loop — autonomous, time-based development agent.

One claude -p call per cycle. Claude has full autonomy within each cycle
to decide what to build, how to build it, and when it's done.

Usage:
    brewin --time 120 "Build an authentication system"
    brewin --time 60 --mode confirm-first
    brewin --resume --time 30
    brewin --status
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from brewin.config import BrewinConfig, load_config, detect_project_type
from brewin.state import BrewinState, StateManager
from brewin.agent import run_cycle

console = Console()


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

BREWIN_SYSTEM_PROMPT = """\
You are Brewin, an autonomous development agent. You advance a software project
toward its goals through iterative development cycles.

You are an intelligent agent, not a step executor. You have a recommended
workflow but the judgment to deviate when appropriate.

## THE BREWIN WORKFLOW (Recommended, Not Required)

  1. WHAT'S NEXT? — Read Mission.md, check git status/log, decide what to build.
  2. DIVE DEEPER — Read source files, understand the codebase before coding.
  3. IMPLEMENT — Write clean, production-ready code. Create/update tests.
  4. AUDIT YOUR WORK — Run git diff, review every change, run tests, fix issues.
  5. DEPLOY — git add, commit with clear message, push.

You have agency:
  - Skip DIVE DEEPER for simple fixes.
  - Reorder phases (run tests mid-implement).
  - Loop back (if tests fail, fix and re-test).
  - Scope down if a task is too big.

## QUALITY GATES (Non-Negotiable)

  - NEVER deploy untested code. Run the test suite before committing.
  - NEVER ignore Mission.md. Every decision must serve the project's purpose.
  - ALWAYS commit your work before ending the cycle.
  - ALWAYS update .brewin/memory.md before ending the cycle (see MEMORY below).
  - ALWAYS end your response with the CYCLE tags (see below).

## TASKS

You have a task backlog at `.brewin/tasks.md`. This is managed by the USER — they
decide what needs to be built. READ IT at the start of every cycle.

The format is simple:
  - [ ] Unchecked items are tasks you should work on (pick the top priority one)
  - [x] Checked items are done — don't repeat them

When you COMPLETE a task, mark it done by changing `- [ ]` to `- [x]`.
When you PARTIALLY complete a task, add a note: `- [ ] Task name (IN PROGRESS: details)`
Do NOT remove tasks or reorder the user's tasks.

After completing a task, ADD exactly 1 new suggested task to the bottom of the
file under a `## Suggested` heading. This task should be something that builds
on what you just shipped — a natural next step enabled by the new feature.
Format: `- [ ] description`

If the tasks file is empty or all tasks are checked off, use your own judgment
based on Mission.md and memory. Pick something high-impact and keep building.
Always keep the project moving forward — an empty backlog is not a reason to stop.

## MEMORY

You have a persistent memory file at `.brewin/memory.md`. This is YOUR knowledge
base — it persists across sessions. READ IT at the start of every cycle.

At the END of every cycle, UPDATE `.brewin/memory.md` with:
  - What you built this cycle and key decisions you made
  - Current state of the project (what works, what's broken, what's incomplete)
  - What should be worked on next (priorities for future cycles)
  - Any gotchas, bugs, or technical debt you noticed
  - Key file paths and architecture notes that would help you ramp up faster

Keep it concise and organized by topic. Don't let it grow past ~200 lines —
prune stale info when you update. This file is your lifeline between sessions.
When you start a new session, this is how you'll know where you left off.

## ENDING A CYCLE

When you're done with this cycle, your LAST lines MUST be exactly:

CYCLE_FOCUS: <one-line description of what you worked on>
CYCLE_OUTCOME: <success|moved_on|wrapped_up|failed>
CYCLE_SUMMARY: <2-3 sentence summary of what you built/changed>

These tags are how the outer loop tracks your progress. Do NOT omit them.
Do NOT put them in markdown formatting. They must be plain text on their own lines.

## DECISION PRINCIPLES

  1. Serve the mission. Every line of code must advance the project's purpose.
  2. Own quality. Audit your own work. Don't ship broken code.
  3. Be efficient. Skip unnecessary work, but never skip testing.
  4. Don't repeat previous cycles — check the cycle history and memory below.
"""


def _read_file_safe(path: str) -> str | None:
    if os.path.isfile(path):
        with open(path) as f:
            return f.read()
    return None


def _build_system_prompt(state: BrewinState, config: BrewinConfig,
                         initial_direction: str | None = None,
                         wrapping_up: bool = False) -> str:
    """Build the full system prompt for a cycle."""
    prompt = BREWIN_SYSTEM_PROMPT
    sections = []

    # Mission
    mission = _read_file_safe(config.mission_file)
    if mission:
        sections.append(f"## Mission (from Mission.md)\n{mission}")
    else:
        sections.append(
            "## Mission\nNo Mission.md found. Create one to give the project direction."
        )

    # CLAUDE.md (Claude Code reads it automatically, but include for context)
    claude_md = _read_file_safe("CLAUDE.md")
    if claude_md:
        sections.append(f"## Conventions (from CLAUDE.md)\n{claude_md}")

    # Tasks — user-managed backlog
    tasks = _read_file_safe(os.path.join(config.state_dir, "tasks.md"))
    if tasks:
        sections.append(f"## Tasks (from .brewin/tasks.md)\n{tasks}")
    else:
        sections.append(
            "## Tasks\nNo task backlog found. Use your own judgment based on "
            "Mission.md and memory to decide what to work on."
        )

    # Memory — persistent knowledge from previous cycles/sessions
    memory = _read_file_safe(os.path.join(config.state_dir, "memory.md"))
    if memory:
        sections.append(f"## Memory (from .brewin/memory.md)\n{memory}")
    else:
        sections.append(
            "## Memory\nNo memory file yet. Create `.brewin/memory.md` at the end "
            "of this cycle to record what you learned."
        )

    # Time
    remaining = state.format_time_remaining(config.time_budget_minutes)
    sections.append(f"## Time Remaining\n{remaining} left in this session.")

    # History
    sections.append(f"## Cycle History\n{state.get_history_summary()}")

    # Direction
    if initial_direction:
        sections.append(
            f"## Direction\nThe user said: \"{initial_direction}\"\n"
            "Use this to guide your work."
        )

    # Wrap-up
    if wrapping_up:
        sections.append(
            "## WRAPPING UP\n"
            "TIME IS ALMOST UP. Do NOT start new features.\n"
            "Commit any uncommitted work, push, and end the cycle cleanly."
        )

    return prompt + "\n\n" + "\n\n".join(sections)


def _parse_tag(text: str, tag: str) -> str:
    """Extract 'TAG: value' from output, handling markdown formatting."""
    for line in reversed(text.splitlines()):
        cleaned = re.sub(r'[*`#>]', '', line).strip()
        prefix = f"{tag}:"
        if cleaned.upper().startswith(prefix.upper()):
            return cleaned[len(prefix):].strip()
    return ""


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_brewin(config: BrewinConfig, initial_direction: str | None = None,
               resume: bool = False):
    mgr = StateManager(config.state_dir)

    if resume:
        state = mgr.load()
        if state.cycle_count == 0:
            console.print("[red]No previous session to resume.[/red]")
            resume = False

    if resume:
        state.start_time = time.time()
        console.print(Panel(
            f"[bold]Resuming Brewin[/bold]\n"
            f"  Cycles done: [cyan]{state.cycle_count}[/cyan]\n"
            f"  New budget:  [cyan]{config.time_budget_minutes}m[/cyan]",
            border_style="yellow",
        ))
    else:
        state = mgr.reset()
        state.start_time = time.time()
        state.project_root = os.getcwd()
        state.session_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    project_type = detect_project_type()

    if not resume:
        console.print(Panel(
            f"[bold]Brewin Loop[/bold] — Autonomous Development Agent\n\n"
            f"  Time budget:  [cyan]{config.time_budget_minutes}m[/cyan]\n"
            f"  Project:      [cyan]{project_type}[/cyan]\n"
            f"  Model:        [cyan]{config.model}[/cyan]\n"
            f"  Mode:         [cyan]{config.autonomy_mode}[/cyan]"
            + (f"\n  Direction:    [green]{initial_direction}[/green]"
               if initial_direction else ""),
            border_style="bold blue",
        ))

    cycle = state.cycle_count

    while not state.is_time_up(config.time_budget_minutes):
        cycle += 1
        cycle_start = time.time()

        if cycle > config.max_cycles:
            console.print("[red]Safety cap reached.[/red]")
            break

        wrapping_up = state.is_wrapping_up(
            config.time_budget_minutes, config.wrap_up_minutes
        )
        remaining = state.format_time_remaining(config.time_budget_minutes)
        label = f"[bold]Cycle {cycle}[/bold] — {remaining} remaining"
        if wrapping_up:
            label += " [yellow](WRAP-UP)[/yellow]"
        console.print(Panel(label, border_style="yellow" if wrapping_up else "cyan"))

        # Confirm-first mode
        if config.autonomy_mode == "confirm-first" and cycle > 1:
            try:
                answer = console.input(
                    "[bold yellow]Continue? (y/n):[/bold yellow] "
                ).strip().lower()
                if answer not in ("y", "yes", ""):
                    console.print("Halted.")
                    break
            except (EOFError, KeyboardInterrupt):
                console.print("\nHalted.")
                break

        # Build prompt and run cycle
        system_prompt = _build_system_prompt(
            state, config,
            initial_direction=initial_direction if cycle == 1 else None,
            wrapping_up=wrapping_up,
        )

        output = run_cycle(
            user_message="Start a new development cycle. What's next?",
            system_prompt=system_prompt,
            model=config.model,
        )

        # Parse cycle results from output
        cycle_duration = time.time() - cycle_start
        focus = _parse_tag(output, "CYCLE_FOCUS") or "Unknown"
        outcome = _parse_tag(output, "CYCLE_OUTCOME") or "completed"
        summary = _parse_tag(output, "CYCLE_SUMMARY") or ""

        state.log_cycle(focus, outcome, summary=summary, duration=cycle_duration)
        mgr.save(state)

        style = "green" if outcome == "success" else "yellow"
        console.print(Panel(
            f"[bold]Cycle {cycle} done[/bold]\n"
            f"  Focus:    {focus}\n"
            f"  Outcome:  {outcome}\n"
            f"  Summary:  {summary}\n"
            f"  Duration: {cycle_duration:.0f}s",
            border_style=style,
        ))

        time.sleep(config.sleep_between_cycles)

    # Session complete
    print_summary(state, config)
    _save_session_log(state, config)
    mgr.save(state)


def print_summary(state: BrewinState, config: BrewinConfig):
    table = Table(title="Brewin Session Summary", border_style="blue")
    table.add_column("Cycle", style="cyan", justify="right")
    table.add_column("Focus", style="white")
    table.add_column("Outcome")
    table.add_column("Duration", justify="right")

    for entry in state.cycle_log:
        style = "green" if entry["outcome"] == "success" else "red"
        table.add_row(
            str(entry["cycle"]),
            entry["focus"],
            f"[{style}]{entry['outcome']}[/{style}]",
            f"{entry.get('duration_seconds', 0):.0f}s",
        )

    console.print()
    console.print(table)

    successful = sum(1 for e in state.cycle_log if e["outcome"] == "success")
    console.print(Panel(
        f"  Cycles: {state.cycle_count}  |  "
        f"Successful: {successful}  |  "
        f"Time: {state.elapsed_minutes():.0f}m / {config.time_budget_minutes}m",
        border_style="bold blue",
    ))


def _save_session_log(state: BrewinState, config: BrewinConfig):
    """Save a session log to .brewin/sessions/ for historical reference."""
    sessions_dir = os.path.join(config.state_dir, "sessions")
    os.makedirs(sessions_dir, exist_ok=True)

    log_file = os.path.join(sessions_dir, f"{state.session_id}.md")
    lines = [
        f"# Brewin Session {state.session_id}",
        f"",
        f"- Project: {state.project_root}",
        f"- Duration: {state.elapsed_minutes():.0f}m / {config.time_budget_minutes}m budget",
        f"- Model: {config.model}",
        f"- Cycles: {state.cycle_count}",
        f"",
        f"## Cycles",
        f"",
    ]
    for e in state.cycle_log:
        status = "+" if e["outcome"] == "success" else "x"
        lines.append(f"### {status} Cycle {e['cycle']}: {e['focus']}")
        lines.append(f"- Outcome: {e['outcome']}")
        lines.append(f"- Duration: {e.get('duration_seconds', 0):.0f}s")
        if e.get("summary"):
            lines.append(f"- Summary: {e['summary']}")
        lines.append("")

    with open(log_file, "w") as f:
        f.write("\n".join(lines))
    console.print(f"  [dim]Session log saved to {log_file}[/dim]")


def show_status(config: BrewinConfig):
    mgr = StateManager(config.state_dir)
    state = mgr.load()
    if state.cycle_count == 0:
        console.print("[dim]No Brewin session found.[/dim]")
        return
    console.print(Panel(
        f"  Session: {state.session_id}\n"
        f"  Cycles:  {state.cycle_count}\n"
        f"  Project: {state.project_root}",
        title="Brewin Status",
        border_style="blue",
    ))
    console.print(state.get_history_summary())


def main():
    parser = argparse.ArgumentParser(description="Brewin Loop — autonomous development agent")
    parser.add_argument("direction", nargs="*", default=[])
    parser.add_argument("--time", "-t", type=int, default=60)
    parser.add_argument("--mode", "-m", choices=["autonomous", "confirm-first"],
                        default="autonomous")
    parser.add_argument("--model", default=None)
    parser.add_argument("--project", "-p", default=".")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--resume", action="store_true")

    args = parser.parse_args()

    config = load_config(
        time_budget_minutes=args.time,
        autonomy_mode=args.mode,
        model=args.model,
    )

    if args.project != ".":
        os.chdir(args.project)

    if args.status:
        show_status(config)
        return

    direction = " ".join(args.direction) if args.direction else None

    try:
        run_brewin(config, initial_direction=direction, resume=args.resume)
    except KeyboardInterrupt:
        console.print("\n[yellow]Brewin interrupted. State saved.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
