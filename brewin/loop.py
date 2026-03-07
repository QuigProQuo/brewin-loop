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
import json
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
from brewin.agent import run_cycle, CycleResult
from brewin.checkpoint import create_checkpoint, rollback_to_checkpoint, cleanup_checkpoints
from brewin.healthcheck import run_health_check
from brewin.context import get_git_context, get_project_tree, get_health_summary
from brewin.cycles import select_cycle_type
from brewin.hooks import run_hooks, build_hook_env

console = Console()


# ---------------------------------------------------------------------------
# Micro-replan prompt (runs after each work cycle)
# ---------------------------------------------------------------------------

MICRO_REPLAN_PROMPT = """\
You just completed a development cycle. Review what happened and update the task backlog.

## What Just Happened
Cycle focus: {focus}
Cycle outcome: {outcome}
Cycle summary: {summary}

## Current Tasks
{tasks}

## Current Memory
{memory}

## Your Job (Be Quick)

1. If the completed task isn't marked `[x]` yet, mark it done.
2. If you partially completed something, update its status note.
3. If the next priority task is complex, add 2-4 subtasks beneath it.
4. If you discovered blockers, add `(BLOCKED: reason)` to affected tasks.
5. Add any discovered issues under `## Discovered`.
6. Update `.brewin/memory.md` with what you learned this cycle.

Do NOT write application code. Only update `.brewin/tasks.md` and `.brewin/memory.md`.

End with:
```json
{{"cycle_focus": "micro-replan", "cycle_outcome": "success", "cycle_summary": "<what you updated>"}}
```
"""


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
  - ALWAYS end your response with the CYCLE JSON block (see below).

## TASKS

You have a task backlog at `.brewin/tasks.md`. This is managed by the USER — they
decide what needs to be built. READ IT at the start of every cycle.

The format is simple:
  - [ ] Unchecked items are tasks you should work on (pick the top priority one)
  - [x] Checked items are done — don't repeat them

When you COMPLETE a task, mark it done by changing `- [ ]` to `- [x]`.
When you PARTIALLY complete a task, add a note: `- [ ] Task name (IN PROGRESS: details)`
Do NOT remove tasks or reorder the user's priority tasks.

### Task Management (Do This Every Cycle)

After completing or making progress on a task, update `.brewin/tasks.md`:

1. **Break down upcoming work.** If the next unchecked task is complex (multi-file,
   multi-step), add subtasks indented beneath it:
   ```
   - [ ] Build HealthKit importer
     - [ ] Generalize HealthKitGlucosePoller pattern
     - [ ] Add body composition import
     - [ ] Add workout import
     - [ ] Deduplication by (timestamp, source)
   ```

2. **Flag blockers.** If you discover something that blocks a future task, add a
   note directly on the task:
   ```
   - [ ] Add body composition import (BLOCKED: needs HealthKit entitlement for HKBodyFatPercentage)
   ```

3. **Suggest next steps.** Add 1-2 suggested tasks under `## Suggested` that build
   on what you just shipped — natural next steps enabled by the new work.
   Format: `- [ ] description`

4. **Note discoveries.** If you find technical debt, missing tests, or architecture
   issues while working, add them under `## Discovered`:
   ```
   ## Discovered
   - [ ] HealthKitManager.swift has no error handling for denied permissions
   - [ ] DatabaseMigrations.swift needs index on timestamp columns
   ```

Do NOT remove or reorder the user's priority tasks. Your additions go in
`## Suggested` and `## Discovered` sections at the bottom.

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

When you're done with this cycle, your LAST lines MUST be a JSON block:

```json
{"cycle_focus": "<one-line description>", "cycle_outcome": "<success|moved_on|wrapped_up|failed>", "cycle_summary": "<2-3 sentence summary>"}
```

These fields are how the outer loop tracks your progress. Do NOT omit them.

Fallback: If you cannot output JSON, use these plain-text tags on their own lines:
CYCLE_FOCUS: <description>
CYCLE_OUTCOME: <outcome>
CYCLE_SUMMARY: <summary>

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


def _run_micro_replan(
    state: BrewinState, config: BrewinConfig,
    focus: str, outcome: str, summary: str,
) -> CycleResult | None:
    """Run a quick, cheap replan call to update tasks and memory after a work cycle."""
    tasks = _read_file_safe(os.path.join(config.state_dir, "tasks.md")) or "(empty)"
    memory = _read_file_safe(os.path.join(config.state_dir, "memory.md")) or "(empty)"

    prompt = MICRO_REPLAN_PROMPT.format(
        focus=focus, outcome=outcome, summary=summary,
        tasks=tasks, memory=memory,
    )

    console.print("  [dim]Running micro-replan...[/dim]")
    result = run_cycle(
        user_message=prompt,
        system_prompt=(
            "You are Brewin's task planner. You update task backlogs and memory files. "
            "You do NOT write application code. Be concise and fast."
        ),
        model=config.replan_model or config.model,
        session_id=state.claude_session_id if state.claude_session_id else None,
        continue_session=bool(state.claude_session_id),
        timeout=120,
    )

    if result.is_error:
        console.print("  [yellow]Micro-replan failed (non-critical, continuing)[/yellow]")
        return None

    console.print("  [dim]Micro-replan complete.[/dim]")
    return result


def _build_system_prompt(state: BrewinState, config: BrewinConfig,
                         initial_direction: str | None = None,
                         wrapping_up: bool = False,
                         cycle_type_addendum: str = "",
                         health_context: str = "",
                         timeout_context: str = "") -> str:
    """Build the full system prompt for cycle 1."""
    prompt = BREWIN_SYSTEM_PROMPT
    sections = []

    # Cycle type mode
    if cycle_type_addendum:
        sections.append(cycle_type_addendum)

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

    # Git context
    git_ctx = get_git_context()
    if git_ctx:
        sections.append(f"## Recent Git Activity\n{git_ctx}")

    # Project structure (only on first cycle to save tokens)
    if state.cycle_count == 0:
        tree = get_project_tree()
        if tree:
            sections.append(f"## Project Structure\n```\n{tree}\n```")

    # Health check results from previous cycle
    if health_context:
        sections.append(f"## Project Health\n{health_context}")

    # Timeout context from previous cycle
    if timeout_context:
        sections.append(f"## Previous Cycle Stalled\n{timeout_context}")

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

    full_prompt = prompt + "\n\n" + "\n\n".join(sections)

    # Dynamic prompt sizing — truncate if too long
    if len(full_prompt) > config.max_prompt_chars:
        # Rebuild without project tree and truncate history
        sections = [s for s in sections if not s.startswith("## Project Structure")]
        full_prompt = prompt + "\n\n" + "\n\n".join(sections)

    return full_prompt


def _build_continuation_prompt(state: BrewinState, config: BrewinConfig,
                                wrapping_up: bool = False) -> str:
    """Build a lightweight prompt for cycles 2+ (session already has full context)."""
    remaining = state.format_time_remaining(config.time_budget_minutes)
    parts = [
        f"Continue. {remaining} remaining in this session. "
        f"Starting cycle {state.cycle_count + 1}.",
    ]

    if wrapping_up:
        parts.append(
            "TIME IS ALMOST UP. Commit all work, update memory, and wrap up."
        )

    # Include fresh tasks in case user updated them between cycles
    tasks = _read_file_safe(os.path.join(config.state_dir, "tasks.md"))
    if tasks:
        parts.append(f"\nCurrent tasks (.brewin/tasks.md):\n{tasks}")

    # Include fresh memory in case it was updated
    memory = _read_file_safe(os.path.join(config.state_dir, "memory.md"))
    if memory:
        parts.append(f"\nMemory (.brewin/memory.md):\n{memory}")

    return "\n\n".join(parts)


def _parse_cycle_result(text: str) -> dict:
    """Extract structured cycle result from output. Tries JSON block first,
    falls back to tag parsing."""
    # Try JSON block
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if all(k in data for k in ("cycle_focus", "cycle_outcome", "cycle_summary")):
                return data
        except json.JSONDecodeError:
            pass

    # Try bare JSON on last lines
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                if "cycle_focus" in data:
                    return data
            except json.JSONDecodeError:
                continue

    # Fallback: tag parsing (backward compat)
    return {
        "cycle_focus": _parse_tag(text, "CYCLE_FOCUS") or "Unknown",
        "cycle_outcome": _parse_tag(text, "CYCLE_OUTCOME") or "completed",
        "cycle_summary": _parse_tag(text, "CYCLE_SUMMARY") or "",
    }


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
            f"  New budget:  [cyan]{config.time_budget_minutes}m[/cyan]\n"
            f"  Session:     [dim]{state.session_id}[/dim]",
            border_style="yellow",
        ))
    else:
        state = mgr.reset()
        state.start_time = time.time()
        state.project_root = os.getcwd()
        state.session_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        state.claude_session_id = ""

    project_type = detect_project_type()

    if not resume:
        console.print(Panel(
            f"[bold]Brewin Loop[/bold] — Autonomous Development Agent\n\n"
            f"  Time budget:  [cyan]{config.time_budget_minutes}m[/cyan]\n"
            f"  Project:      [cyan]{project_type}[/cyan]\n"
            f"  Model:        [cyan]{config.model}[/cyan]\n"
            f"  Mode:         [cyan]{config.autonomy_mode}[/cyan]\n"
            f"  Session:      [dim]{state.session_id}[/dim]"
            + (f"\n  Direction:    [green]{initial_direction}[/green]"
               if initial_direction else ""),
            border_style="bold blue",
        ))

    cycle = state.cycle_count
    last_outcome: str | None = None
    last_health_context = ""
    last_timeout_context = ""
    consecutive_stalls = 0
    consecutive_failures = 0

    while not state.is_time_up(config.time_budget_minutes):
        cycle += 1
        cycle_start = time.time()

        if cycle > config.max_cycles:
            console.print("[red]Safety cap reached.[/red]")
            break

        wrapping_up = state.is_wrapping_up(
            config.time_budget_minutes, config.wrap_up_minutes
        )

        # Select cycle type
        cycle_type = select_cycle_type(
            cycle, last_outcome, wrapping_up,
            override=config.cycle_type_override,
            consecutive_stalls=consecutive_stalls,
        )

        remaining = state.format_time_remaining(config.time_budget_minutes)
        label = (
            f"[bold]Cycle {cycle}[/bold] [{cycle_type.name}] — "
            f"{remaining} remaining"
        )
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

        # Pre-cycle hooks
        hook_env = build_hook_env(
            cycle=cycle, session_id=state.session_id,
            time_remaining=remaining,
        )
        run_hooks(config.pre_cycle_hooks, "pre-cycle", env_extras=hook_env)

        # Git checkpoint
        checkpoint = create_checkpoint(cycle, state.session_id)

        # Build prompt and run cycle
        # Always send system prompt (safety net if session continuity fails).
        # Cycle 1: full prompt + direction. Cycles 2+: try session continuity
        # with a continuation user message.
        is_first_cycle = (cycle == 1) or not state.claude_session_id
        use_session_continuity = not is_first_cycle

        # Always build system prompt — session continuity may not work in -p mode
        system_prompt = _build_system_prompt(
            state, config,
            initial_direction=initial_direction if is_first_cycle else None,
            wrapping_up=wrapping_up,
            cycle_type_addendum=cycle_type.prompt_addendum,
            health_context=last_health_context,
            timeout_context=last_timeout_context,
        )

        if is_first_cycle:
            user_message = "Start a new development cycle. What's next?"
        else:
            user_message = _build_continuation_prompt(
                state, config, wrapping_up=wrapping_up,
            )
            # Prepend cycle type instructions to continuation prompt
            if cycle_type.prompt_addendum:
                user_message = cycle_type.prompt_addendum + "\n\n" + user_message
            # Include health context if available
            if last_health_context:
                user_message += f"\n\n## Project Health\n{last_health_context}"
            # Include timeout context if previous cycle stalled
            if last_timeout_context:
                user_message += f"\n\n## Previous Cycle Stalled\n{last_timeout_context}"

        # Use config.cycle_timeout if set, otherwise cycle type timeout (usually None)
        effective_timeout = config.cycle_timeout if config.cycle_timeout is not None else cycle_type.timeout

        cycle_result = run_cycle(
            user_message=user_message,
            system_prompt=system_prompt,
            model=config.model,
            session_id=state.claude_session_id if use_session_continuity else None,
            continue_session=use_session_continuity,
            timeout=effective_timeout,
        )

        # Update session ID from Claude's response (in case it changed)
        if cycle_result.session_id:
            state.claude_session_id = cycle_result.session_id

        # Parse cycle results from output
        cycle_duration = time.time() - cycle_start
        parsed = _parse_cycle_result(cycle_result.output)
        focus = parsed.get("cycle_focus", "Unknown")
        outcome = parsed.get("cycle_outcome", "completed")
        summary = parsed.get("cycle_summary", "")

        # Override outcome if the cycle was killed/errored
        if cycle_result.is_error:
            if cycle_result.timeout_type == "stall":
                outcome = "stalled"
                if not summary:
                    summary = "Cycle stalled (no output for 5 min, work auto-saved)"
            elif cycle_result.timeout_type == "duration":
                outcome = "timed_out"
                if not summary:
                    summary = "Cycle hit duration limit (work auto-saved)"
            elif outcome not in ("failed",):
                outcome = "failed"
                if not summary:
                    summary = "Cycle terminated abnormally"

        # Independent health check
        health = run_health_check(
            build_cmd=config.health_check_build,
            test_cmd=config.health_check_test,
            timeout=config.health_check_timeout,
        )

        # Build health context for next cycle's prompt
        last_health_context = get_health_summary(
            health.build_ok, health.tests_ok, health.test_output,
        )

        # Rollback on verified failure — but NOT when partial work was saved
        # (stalled/timed_out cycles have auto-saved WIP commits to preserve)
        has_saved_partial = cycle_result.timeout_type in ("stall", "duration")
        if (not health.passed and config.rollback_on_failure
                and checkpoint.success and not has_saved_partial):
            console.print(
                f"[red]Health check failed after cycle {cycle}. "
                f"Rolling back to {checkpoint.tag}[/red]"
            )
            rollback_to_checkpoint(checkpoint.tag)
            outcome = "failed"
            summary += " (rolled back — health check failed)"
            # Reset Claude session — its context is now stale after rollback
            state.claude_session_id = ""
            console.print("  [dim]Session reset (rollback invalidated context)[/dim]")

        # Reset session on failure so next cycle gets a fresh full prompt
        if outcome == "failed" and state.claude_session_id:
            state.claude_session_id = ""
            console.print("  [dim]Session reset (cycle failed)[/dim]")

        last_outcome = outcome

        # Consecutive failure cap — stop burning cycles on structural failures
        if outcome == "failed":
            consecutive_failures += 1
            if consecutive_failures >= 3:
                console.print(
                    "[red]3 consecutive failures — stopping to avoid "
                    "wasting cycles.[/red]"
                )
                break
        else:
            consecutive_failures = 0

        # Build timeout context for the next cycle if this one stalled/timed out
        if outcome in ("stalled", "timed_out"):
            consecutive_stalls += 1
            timeout_parts = [
                f"The previous cycle (cycle {cycle}, type={cycle_type.name}) "
                f"{'stalled' if outcome == 'stalled' else 'hit its duration limit'} "
                f"after {cycle_duration:.0f}s.",
                f"It was working on: {focus}",
            ]
            if cycle_result.partial_diff_stat:
                timeout_parts.append(
                    f"\nPartial work saved (auto-committed):\n"
                    f"```\n{cycle_result.partial_diff_stat}\n```"
                )
            if cycle_result.partial_diff:
                timeout_parts.append(
                    f"\nActual changes (diff):\n"
                    f"```diff\n{cycle_result.partial_diff}\n```"
                )
            if cycle_result.output:
                last_output = cycle_result.output[-1000:]
                timeout_parts.append(
                    f"\nLast output from the interrupted cycle:\n"
                    f"```\n{last_output}\n```"
                )
            last_timeout_context = "\n".join(timeout_parts)
        else:
            consecutive_stalls = 0
            last_timeout_context = ""

        state.log_cycle(
            focus, outcome,
            summary=summary,
            duration=cycle_duration,
            input_tokens=cycle_result.input_tokens,
            output_tokens=cycle_result.output_tokens,
            cost_usd=cycle_result.cost_usd,
        )
        mgr.save(state)

        style = "green" if outcome == "success" else "yellow"
        if outcome in ("failed", "stalled", "timed_out"):
            style = "red" if outcome == "failed" else "yellow"
        tokens_str = f"{cycle_result.input_tokens:,}in / {cycle_result.output_tokens:,}out"
        health_str = ""
        if health.build_ok is not None or health.tests_ok is not None:
            health_str = (
                f"\n  Health:   build={'pass' if health.build_ok else 'FAIL' if health.build_ok is not None else 'n/a'}"
                f" tests={'pass' if health.tests_ok else 'FAIL' if health.tests_ok is not None else 'n/a'}"
            )
        console.print(Panel(
            f"[bold]Cycle {cycle} done[/bold] [{cycle_type.name}]\n"
            f"  Focus:    {focus}\n"
            f"  Outcome:  {outcome}\n"
            f"  Summary:  {summary}\n"
            f"  Duration: {cycle_duration:.0f}s\n"
            f"  Tokens:   {tokens_str}\n"
            f"  Cost:     ${cycle_result.cost_usd:.4f}"
            + health_str,
            border_style=style,
        ))

        # Post-cycle hooks
        hook_env.update({"BREWIN_OUTCOME": outcome, "BREWIN_FOCUS": focus})
        run_hooks(config.post_cycle_hooks, "post-cycle", env_extras=hook_env)

        # Micro-replan: quick task update after work cycles (not after replan/planning)
        if (config.micro_replan
                and cycle_type.name in ("deep_work", "quick_fix", "continue_work")
                and outcome != "failed"
                and not wrapping_up):
            replan_result = _run_micro_replan(
                state, config, focus, outcome, summary,
            )
            if replan_result:
                state.total_input_tokens += replan_result.input_tokens
                state.total_output_tokens += replan_result.output_tokens
                state.total_cost_usd += replan_result.cost_usd
                mgr.save(state)

        time.sleep(config.sleep_between_cycles)

    # Session complete
    print_summary(state, config)
    _save_session_log(state, config)
    mgr.save(state)

    # Post-session hooks
    run_hooks(config.post_session_hooks, "post-session", env_extras=build_hook_env(
        cycle=state.cycle_count, session_id=state.session_id,
        outcome=last_outcome or "",
    ))

    # Cleanup checkpoints on successful sessions
    failed_count = sum(1 for e in state.cycle_log if e["outcome"] == "failed")
    if failed_count == 0:
        cleanup_checkpoints(state.session_id)


def print_summary(state: BrewinState, config: BrewinConfig):
    table = Table(title="Brewin Session Summary", border_style="blue")
    table.add_column("Cycle", style="cyan", justify="right")
    table.add_column("Focus", style="white")
    table.add_column("Outcome")
    table.add_column("Duration", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")

    for entry in state.cycle_log:
        style = "green" if entry["outcome"] == "success" else "red"
        in_tok = entry.get("input_tokens", 0)
        out_tok = entry.get("output_tokens", 0)
        cost = entry.get("cost_usd", 0.0)
        table.add_row(
            str(entry["cycle"]),
            entry["focus"],
            f"[{style}]{entry['outcome']}[/{style}]",
            f"{entry.get('duration_seconds', 0):.0f}s",
            f"{in_tok:,}/{out_tok:,}",
            f"${cost:.4f}",
        )

    console.print()
    console.print(table)

    successful = sum(1 for e in state.cycle_log if e["outcome"] == "success")
    console.print(Panel(
        f"  Cycles: {state.cycle_count}  |  "
        f"Successful: {successful}  |  "
        f"Time: {state.elapsed_minutes():.0f}m / {config.time_budget_minutes}m  |  "
        f"Tokens: {state.total_input_tokens:,}in / {state.total_output_tokens:,}out  |  "
        f"Cost: ${state.total_cost_usd:.4f}",
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
        f"- Tokens: {state.total_input_tokens:,} in / {state.total_output_tokens:,} out",
        f"- Cost: ${state.total_cost_usd:.4f}",
        f"",
        f"## Cycles",
        f"",
    ]
    for e in state.cycle_log:
        status = "+" if e["outcome"] == "success" else "x"
        lines.append(f"### {status} Cycle {e['cycle']}: {e['focus']}")
        lines.append(f"- Outcome: {e['outcome']}")
        lines.append(f"- Duration: {e.get('duration_seconds', 0):.0f}s")
        lines.append(f"- Tokens: {e.get('input_tokens', 0):,}in / {e.get('output_tokens', 0):,}out")
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
        f"  Project: {state.project_root}\n"
        f"  Tokens:  {state.total_input_tokens:,}in / {state.total_output_tokens:,}out\n"
        f"  Cost:    ${state.total_cost_usd:.4f}",
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
    parser.add_argument("--cycle-type", choices=["planning", "quick_fix", "deep_work", "review", "replan"],
                        default=None, help="Force a specific cycle type for all cycles")
    parser.add_argument("--no-rollback", action="store_true",
                        help="Disable automatic rollback on health check failure")
    parser.add_argument("--no-replan", action="store_true",
                        help="Disable micro-replan after each cycle")
    parser.add_argument("--replan-interval", type=int, default=None,
                        help="Insert full replan cycle every N work cycles (0=disabled)")

    args = parser.parse_args()

    config = load_config(
        time_budget_minutes=args.time,
        autonomy_mode=args.mode,
        model=args.model,
        cycle_type_override=args.cycle_type,
    )

    if args.no_rollback:
        config.rollback_on_failure = False
    if args.no_replan:
        config.micro_replan = False
    if args.replan_interval is not None:
        config.replan_interval = args.replan_interval

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
