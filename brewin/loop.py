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
import signal
import subprocess
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
from brewin.healthcheck import run_health_check, health_regressed, is_likely_config_error, HealthCheckResult
from brewin.context import (
    get_git_context, get_project_tree, get_health_summary,
    get_recently_changed_files, load_structured_memory, has_architecture_map,
    load_shared_discoveries,
)
from brewin.cycles import select_cycle_type
from brewin.hooks import run_hooks, build_hook_env
from brewin.worktree import create_agent_worktree, remove_agent_worktree, get_agent_branch
from brewin.prompts import (
    BREWIN_SYSTEM_PROMPT, MICRO_REPLAN_PROMPT,
    PUA_OVERLAY_PROMPT, PUA_MICRO_REPLAN_PROMPT,
)

console = Console()

# Graceful shutdown flag — set by SIGINT/SIGTERM handler, checked between cycles
_shutdown_requested = False


def _request_shutdown(signum, frame):
    """Signal handler that sets the shutdown flag instead of raising KeyboardInterrupt."""
    global _shutdown_requested
    _shutdown_requested = True
    sig_name = signal.Signals(signum).name
    console.print(f"\n[yellow]Received {sig_name} — will stop after current cycle finishes.[/yellow]")


def _read_file_safe(path: str) -> str | None:
    if os.path.isfile(path):
        with open(path) as f:
            return f.read()
    return None


def _cleanup_dirty_state(work_dir: str | None) -> None:
    """Reset uncommitted changes left by failed WIP commits or lint-staged hooks.
    Only touches tracked files — won't delete new untracked files."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=work_dir, timeout=10,
        )
        if not status.stdout.strip():
            return
        # Unstage anything that got staged by a failed commit attempt
        subprocess.run(
            ["git", "reset", "HEAD", "--quiet"],
            capture_output=True, cwd=work_dir, timeout=10,
        )
        # Discard modifications to tracked files (not untracked)
        subprocess.run(
            ["git", "checkout", "--", "."],
            capture_output=True, cwd=work_dir, timeout=10,
        )
        console.print("  [dim]Cleaned up dirty state before health check[/dim]")
    except Exception:
        pass  # Non-critical — health check will run anyway


def _migrate_memory(state_dir: str) -> None:
    """Migrate flat memory.md to structured memory/ directory."""
    old_path = os.path.join(state_dir, "memory.md")
    memory_dir = os.path.join(state_dir, "memory")
    new_path = os.path.join(memory_dir, "state.md")

    if not os.path.isfile(old_path):
        return
    if os.path.isdir(memory_dir) and os.path.isfile(new_path):
        return  # Already migrated

    os.makedirs(memory_dir, exist_ok=True)
    content = _read_file_safe(old_path) or ""
    with open(new_path, "w") as f:
        f.write(content)
    os.remove(old_path)
    console.print(f"  [dim]Migrated memory.md → memory/state.md[/dim]")


def _fallback_memory_update(
    config: BrewinConfig, cycle: int, focus: str, outcome: str, summary: str,
) -> None:
    """Append cycle results directly to memory/state.md when micro-replan fails.
    Ensures context is never lost even if the replan subprocess crashes."""
    state_file = os.path.join(config.state_dir, "memory", "state.md")
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n## Cycle {cycle} ({timestamp})\n"
        f"- **Focus:** {focus}\n"
        f"- **Outcome:** {outcome}\n"
        f"- **Summary:** {summary}\n"
    )
    try:
        with open(state_file, "a") as f:
            f.write(entry)
        console.print("  [dim]Fallback: appended cycle results to memory/state.md[/dim]")
    except Exception as e:
        console.print(f"  [dim red]Fallback memory write failed: {e}[/dim red]")


_DISCOVERY_INSTRUCTIONS = (
    "10. **Discoveries for other agents:** If this cycle uncovered information that "
    "would be useful to other agents working on this project (API patterns, auth "
    "mechanisms, config details, dependency constraints, architectural decisions), "
    "emit one DISCOVERY line per finding in this format:\n"
    "DISCOVERY[type|tag1,tag2]: description of the finding\n"
    "Types: architecture, api, config, dependency, convention, bug\n"
    "Example: DISCOVERY[architecture|auth]: Auth uses RS256 JWT, public key at /keys/jwt-public.pem"
)


def _extract_discoveries(output: str, config: BrewinConfig) -> None:
    """Parse DISCOVERY[] lines from cycle output and write to shared feed."""
    if not config.agent_name:
        return

    from brewin.discoveries import write_discovery, brewin_dir_from_state_dir
    brewin_dir = brewin_dir_from_state_dir(config.state_dir)

    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("DISCOVERY["):
            continue
        try:
            # DISCOVERY[type|tag1,tag2]: content
            bracket_end = line.index("]")
            meta = line[len("DISCOVERY["):bracket_end]
            content = line[bracket_end + 1:].lstrip(": ")

            parts = meta.split("|", 1)
            discovery_type = parts[0].strip()
            tags = [t.strip() for t in parts[1].split(",")] if len(parts) > 1 else []

            if content:
                write_discovery(
                    agent_name=config.agent_name,
                    content=content,
                    discovery_type=discovery_type,
                    tags=tags,
                    brewin_dir=brewin_dir,
                )
                console.print(f"  [dim]Discovery shared: [{discovery_type}] {content[:60]}[/dim]")
        except (ValueError, IndexError):
            continue


def _run_micro_replan(
    state: BrewinState, config: BrewinConfig,
    focus: str, outcome: str, summary: str,
) -> CycleResult | None:
    """Run a quick, cheap replan call to update tasks and memory after a work cycle."""
    tasks = _read_file_safe(os.path.join(config.state_dir, "tasks.md")) or "(empty)"
    mem = load_structured_memory(config.state_dir)

    # Include discovery instructions when running in agent mode (parallel)
    discovery_instructions = _DISCOVERY_INSTRUCTIONS if config.agent_name else ""

    template = PUA_MICRO_REPLAN_PROMPT if config.pua else MICRO_REPLAN_PROMPT
    prompt = template.format(
        focus=focus, outcome=outcome, summary=summary,
        tasks=tasks,
        memory_architecture=mem.get("architecture") or "(empty)",
        memory_decisions=mem.get("decisions") or "(empty)",
        memory_state=mem.get("state") or "(empty)",
        memory_learnings=mem.get("learnings") or "(empty)",
        discovery_instructions=discovery_instructions,
    )

    replan_system = (
        "You are Brewin's task planner. You update task backlogs and memory files. "
        "You do NOT write application code. Be concise and fast."
    )
    if config.pua:
        replan_system += (
            " You also evaluate cycle quality for underperformance patterns "
            "(brute-force retries, blame-shifting, idle tools, busywork). "
            "Capture failure analysis and alternative approaches in memory."
        )
    console.print("  [dim]Running micro-replan...[/dim]")
    result = run_cycle(
        user_message=prompt,
        system_prompt=replan_system,
        model=config.replan_model or config.model,
        timeout=120,
    )

    if result.is_error:
        console.print("  [yellow]Micro-replan failed — using fallback memory update[/yellow]")
        _fallback_memory_update(
            config, state.cycle_count + 1, focus, outcome, summary,
        )
        return None

    # Extract and share discoveries from micro-replan output
    _extract_discoveries(result.output, config)

    console.print("  [dim]Micro-replan complete.[/dim]")
    return result


def _build_system_prompt(state: BrewinState, config: BrewinConfig,
                         initial_direction: str | None = None,
                         wrapping_up: bool = False,
                         cycle_type_addendum: str = "",
                         health_context: str = "",
                         timeout_context: str = "") -> str:
    """Build the full system prompt (sent fresh every cycle)."""
    prompt = BREWIN_SYSTEM_PROMPT
    # Replace .brewin/ references with agent-specific paths when in agent mode
    if config.agent_name:
        state_dir = config.state_dir
        prompt = prompt.replace(".brewin/tasks.md", f"{state_dir}/tasks.md")
        prompt = prompt.replace(".brewin/memory/", f"{state_dir}/memory/")
    sections = []

    # PUA overlay — behavioral rules injected into ALL cycles when enabled
    if config.pua:
        sections.append(PUA_OVERLAY_PROMPT)

    # Cycle type mode
    if cycle_type_addendum:
        sections.append(cycle_type_addendum)

    # Mission — agent-specific mission.md takes priority over root Mission.md
    agent_mission = None
    if config.agent_name:
        agent_mission = _read_file_safe(os.path.join(config.state_dir, "mission.md"))
    root_mission = _read_file_safe(config.mission_file)

    if agent_mission:
        sections.append(f"## Agent Mission (from {config.state_dir}/mission.md)\n{agent_mission}")
        if root_mission:
            sections.append(f"## Project Mission (from Mission.md)\n{root_mission}")
    elif root_mission:
        sections.append(f"## Mission (from Mission.md)\n{root_mission}")
    else:
        sections.append(
            "## Mission\nNo Mission.md found. Create one to give the project direction."
        )

    # CLAUDE.md (Claude Code reads it automatically, but include for context)
    claude_md = _read_file_safe("CLAUDE.md")
    if claude_md:
        sections.append(f"## Conventions (from CLAUDE.md)\n{claude_md}")

    # Tasks — user-managed backlog
    tasks_path = os.path.join(config.state_dir, "tasks.md")
    tasks = _read_file_safe(tasks_path)
    if tasks:
        sections.append(f"## Tasks (from {tasks_path})\n{tasks}")
    else:
        sections.append(
            "## Tasks\nNo task backlog found. Use your own judgment based on "
            "Mission.md and memory to decide what to work on."
        )

    # Memory — structured persistent knowledge from previous cycles/sessions
    memory_dir = os.path.join(config.state_dir, "memory")
    mem = load_structured_memory(config.state_dir)
    has_any_memory = any(mem.values())
    if has_any_memory:
        mem_parts = []
        if mem.get("architecture"):
            mem_parts.append(f"### Architecture ({memory_dir}/architecture.md)\n{mem['architecture']}")
        if mem.get("state"):
            mem_parts.append(f"### State ({memory_dir}/state.md)\n{mem['state']}")
        if mem.get("decisions"):
            mem_parts.append(f"### Decisions ({memory_dir}/decisions.md)\n{mem['decisions']}")
        if mem.get("learnings"):
            mem_parts.append(f"### Learnings ({memory_dir}/learnings.md)\n{mem['learnings']}")
        sections.append("## Memory\n" + "\n\n".join(mem_parts))
    else:
        sections.append(
            f"## Memory\nNo memory files yet. Create files in `{memory_dir}/` at the "
            "end of this cycle (see MEMORY section above for file names)."
        )

    # Discoveries from other agents (parallel mode only)
    if config.agent_name:
        discoveries = load_shared_discoveries(
            config.agent_name, state_dir=config.state_dir,
        )
        if discoveries:
            sections.append(f"## Discoveries from Other Agents\n{discoveries}")

    # Git context
    git_ctx = get_git_context()
    if git_ctx:
        sections.append(f"## Recent Git Activity\n{git_ctx}")

    # File change frequency — gives spatial awareness every cycle
    freq = get_recently_changed_files()
    if freq:
        sections.append(f"## Active Development Areas\n{freq}")

    # Project structure (first cycle + explore cycles)
    is_explore = cycle_type_addendum and "EXPLORE" in cycle_type_addendum.upper()
    if state.cycle_count == 0 or is_explore:
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

    # Dynamic prompt sizing — drop sections in priority order if too long
    if len(full_prompt) > config.max_prompt_chars:
        # Drop in order: project structure, decisions, active dev areas, learnings
        drop_order = [
            "## Project Structure",
            "## Discoveries from Other Agents",
            "### Decisions",
            "## Active Development Areas",
            "### Learnings",
        ]
        for prefix in drop_order:
            if len(full_prompt) <= config.max_prompt_chars:
                break
            sections = [s for s in sections if not s.startswith(prefix)]
            full_prompt = prompt + "\n\n" + "\n\n".join(sections)
        if len(full_prompt) > config.max_prompt_chars:
            sections.append(
                "## Note\nSome context was omitted to fit prompt size limits. "
                "Use `find . -type f` or `ls -R` if you need to explore the file tree."
            )
            full_prompt = prompt + "\n\n" + "\n\n".join(sections)

    return full_prompt


def _build_continuation_prompt(state: BrewinState, config: BrewinConfig,
                                wrapping_up: bool = False) -> str:
    """Build the user message for cycles 2+.

    Tasks, memory, and cycle type instructions are already in the system
    prompt (sent fresh every cycle), so this just signals continuation.
    """
    remaining = state.format_time_remaining(config.time_budget_minutes)
    parts = [
        f"Continue. {remaining} remaining in this session. "
        f"Starting cycle {state.cycle_count + 1}.",
    ]

    if wrapping_up:
        parts.append(
            "TIME IS ALMOST UP. Commit all work, update memory, and wrap up."
        )

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
    # Install signal handlers for graceful shutdown
    global _shutdown_requested
    _shutdown_requested = False
    prev_sigint = signal.signal(signal.SIGINT, _request_shutdown)
    prev_sigterm = signal.signal(signal.SIGTERM, _request_shutdown)

    # Resolve state_dir early for agents (must be absolute before any chdir)
    if config.agent_name:
        config.state_dir = os.path.abspath(config.state_dir)
        config.mission_file = os.path.abspath(config.mission_file)
    mgr = StateManager(config.state_dir)
    project_root = os.getcwd()
    worktree_dir = None

    if resume:
        state = mgr.load()
        if state.cycle_count == 0:
            console.print("[red]No previous session to resume.[/red]")
            resume = False

    if resume:
        state.start_time = time.time()
        agent_label = f" [bold magenta]({config.agent_name})[/bold magenta]" if config.agent_name else ""
        console.print(Panel(
            f"[bold]Resuming Brewin[/bold]{agent_label}\n"
            f"  Cycles done: [cyan]{state.cycle_count}[/cyan]\n"
            f"  New budget:  [cyan]{config.time_budget_minutes}m[/cyan]\n"
            f"  Session:     [dim]{state.session_id}[/dim]",
            border_style="yellow",
        ))

        # For agent resume, check for existing worktree
        if config.agent_name:
            wt_path = os.path.join(project_root, ".brewin", "worktrees", config.agent_name)
            if os.path.isdir(wt_path):
                worktree_dir = os.path.abspath(wt_path)
                os.chdir(worktree_dir)
                console.print(f"  [dim]Resumed in worktree: {worktree_dir}[/dim]")
    else:
        state = mgr.reset()
        state.start_time = time.time()
        state.project_root = os.getcwd()
        state.session_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")

        # Create worktree for agent mode
        if config.agent_name:
            worktree_dir = create_agent_worktree(config.agent_name, project_root)
            os.chdir(worktree_dir)
            state.project_root = worktree_dir

    project_type = detect_project_type()

    if not resume:
        agent_label = ""
        agent_info = ""
        if config.agent_name:
            agent_label = f" [bold magenta]Agent: {config.agent_name}[/bold magenta]\n"
            branch = get_agent_branch(config.agent_name, project_root)
            if branch:
                agent_info = f"\n  Branch:       [magenta]{branch}[/magenta]"
            if worktree_dir:
                agent_info += f"\n  Worktree:     [dim]{worktree_dir}[/dim]"

        console.print(Panel(
            f"[bold]Brewin Loop[/bold] — Autonomous Development Agent\n"
            f"{agent_label}\n"
            f"  Time budget:  [cyan]{config.time_budget_minutes}m[/cyan]\n"
            f"  Project:      [cyan]{project_type}[/cyan]\n"
            f"  Model:        [cyan]{config.model}[/cyan]\n"
            f"  Mode:         [cyan]{config.autonomy_mode}[/cyan]\n"
            + (f"  PUA:          [red]enabled[/red]\n" if config.pua else "")
            + f"  Session:      [dim]{state.session_id}[/dim]"
            + agent_info
            + (f"\n  Direction:    [green]{initial_direction}[/green]"
               if initial_direction else ""),
            border_style="bold magenta" if config.agent_name else "bold blue",
        ))

    # Worktree setup — install dependencies if running in a worktree
    if worktree_dir and config.worktree_setup:
        console.print(f"[dim]Running worktree setup: {config.worktree_setup}[/dim]")
        try:
            result = subprocess.run(
                config.worktree_setup, shell=True,
                capture_output=True, text=True,
                timeout=300, cwd=worktree_dir,
            )
            if result.returncode == 0:
                console.print("[green]Worktree setup complete.[/green]")
            else:
                console.print(
                    f"[yellow]Worktree setup exited {result.returncode}[/yellow]\n"
                    f"  {result.stderr.strip()[-200:]}"
                )
        except subprocess.TimeoutExpired:
            console.print("[yellow]Worktree setup timed out (300s)[/yellow]")

    try:
        _run_main_loop(config, state, mgr, project_root, worktree_dir,
                        initial_direction, resume)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Saving state...[/yellow]")
        mgr.save(state)
    except Exception as e:
        console.print(f"\n[red]Brewin error: {e}[/red]")
        mgr.save(state)
    finally:
        # Restore original signal handlers
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)
        # Always restore cwd and clean up worktree
        if worktree_dir:
            os.chdir(project_root)
            console.print(f"  [dim]Restored cwd to {project_root}[/dim]")


def _run_main_loop(config: BrewinConfig, state: BrewinState,
                   mgr: StateManager, project_root: str,
                   worktree_dir: str | None,
                   initial_direction: str | None, resume: bool):
    """Core loop logic, separated so run_brewin can wrap it in try/finally."""
    # Migrate flat memory.md to structured memory/ directory
    _migrate_memory(config.state_dir)

    # Baseline health check — know if project is already broken before we start
    # Skip entirely for research workflow (no code to validate)
    baseline_health = HealthCheckResult(passed=True)
    baseline_healthy = True
    if config.workflow == "research":
        console.print("[dim]Research workflow — health checks disabled.[/dim]")
    elif config.health_check_build or config.health_check_test:
        console.print("[dim]Running baseline health check...[/dim]")
        baseline_health = run_health_check(
            build_cmd=config.health_check_build,
            test_cmd=config.health_check_test,
            timeout=config.health_check_timeout,
        )
        baseline_healthy = baseline_health.passed
        if not baseline_healthy:
            if is_likely_config_error(baseline_health):
                output_hint = ""
                if baseline_health.build_output:
                    output_hint += f"\nBuild: {baseline_health.build_output[-200:]}"
                if baseline_health.test_output:
                    output_hint += f"\nTest: {baseline_health.test_output[-200:]}"
                console.print(Panel(
                    "[red bold]Health check looks like a CONFIG ERROR[/red bold]\n"
                    "The commands in .brewin/config.toml appear to reference "
                    "missing files or paths."
                    + output_hint
                    + "\n\nHealth checks disabled for this session. "
                    "Fix .brewin/config.toml and restart.",
                    border_style="red",
                ))
                config.health_check_build = None
                config.health_check_test = None
                baseline_healthy = True
            else:
                console.print(Panel(
                    "[red bold]Baseline health check FAILED[/red bold]\n"
                    "The project is already broken. Entering heal mode to fix "
                    "build/test failures before starting real work.",
                    border_style="red",
                ))

    cycle = state.cycle_count
    last_outcome: str | None = None
    last_health_context = ""
    last_timeout_context = ""
    consecutive_stalls = 0
    consecutive_failures = 0
    consecutive_wrapped_up = 0
    consecutive_heal_successes_but_health_fails = 0
    work_cycles_since_test = 0
    work_cycles_since_cleanup = 0
    work_cycles_since_explore = 0
    work_cycles_since_synthesize = 0
    is_research = config.workflow == "research"

    while not state.is_time_up(config.time_budget_minutes):
        if _shutdown_requested:
            console.print("[yellow]Shutdown requested — stopping gracefully.[/yellow]")
            break

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
            replan_interval=config.replan_interval,
            consecutive_stalls=consecutive_stalls,
            baseline_healthy=baseline_healthy,
            work_cycles_since_test=work_cycles_since_test,
            work_cycles_since_cleanup=work_cycles_since_cleanup,
            has_architecture_map=has_architecture_map(config.state_dir),
            work_cycles_since_explore=work_cycles_since_explore,
            workflow=config.workflow,
            work_cycles_since_synthesize=work_cycles_since_synthesize,
            consecutive_failures=consecutive_failures,
            pua=config.pua,
        )

        remaining = state.format_time_remaining(config.time_budget_minutes)
        label = (
            f"[bold]Cycle {cycle}[/bold] [{cycle_type.name}] — "
            f"{remaining} remaining"
        )
        if wrapping_up:
            label += " [yellow](WRAP-UP)[/yellow]"
        # PUA escalation level indicator
        if cycle_type.name == "pua_pressure":
            pua_trigger = max(consecutive_failures, consecutive_stalls)
            pua_level = min(max(pua_trigger - 1, 1), 4)
            pua_labels = {1: "L1 — Nudge", 2: "L2 — Investigate", 3: "L3 — Checklist", 4: "L4 — All-out"}
            label += f" [red](PUA {pua_labels[pua_level]})[/red]"
        console.print(Panel(label, border_style="red" if cycle_type.name == "pua_pressure" else ("yellow" if wrapping_up else "cyan")))

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

        # Git checkpoint (skip for non-committing cycles and research workflow)
        if cycle_type.name == "spike" or is_research:
            checkpoint = type('obj', (object,), {'success': False, 'tag': ''})()
        else:
            checkpoint = create_checkpoint(cycle, state.session_id)

        # Build prompt and run cycle
        # Every cycle is a fresh claude -p call with full system prompt.
        # Session continuity (-p --session-id) causes instant crashes.
        is_first_cycle = cycle == 1

        # For heal cycles, inject baseline failure details as health context
        heal_health_context = last_health_context
        if cycle_type.name == "heal" and not heal_health_context:
            heal_health_context = get_health_summary(
                baseline_health.build_ok, baseline_health.tests_ok,
                baseline_health.test_output, baseline_health.build_output,
                build_cmd=config.health_check_build,
                test_cmd=config.health_check_test,
            )

        # For PUA pressure cycles, inject escalation level into the addendum
        # Escalation is driven by the worse of consecutive failures or stalls
        effective_addendum = cycle_type.prompt_addendum
        if cycle_type.name == "pua_pressure":
            pua_trigger = max(consecutive_failures, consecutive_stalls)
            pua_level = min(pua_trigger - 1, 4)
            trigger_type = "failure" if consecutive_failures >= consecutive_stalls else "stall"
            pua_escalation = {
                1: (
                    f"### Escalation: L1 — Nudge\n"
                    f"This is consecutive {trigger_type} #{pua_trigger}. Switch to a fundamentally "
                    f"different approach. Whatever you were trying is NOT working."
                ),
                2: (
                    f"### Escalation: L2 — Investigate\n"
                    f"This is consecutive {trigger_type} #{pua_trigger}. You MUST:\n"
                    "- Search the codebase for the error string and read the source\n"
                    "- Read git history for when this code last worked\n"
                    "- Find a working example of a similar pattern in the codebase\n"
                    "Do NOT write any code until you've completed the SMELL and ELEVATE steps."
                ),
                3: (
                    f"### Escalation: L3 — Full Checklist\n"
                    f"This is consecutive {trigger_type} #{pua_trigger}. Execute the 7-Point Systematic "
                    "Checklist above EXHAUSTIVELY. Check every single item. Document your "
                    "findings for each point before attempting any fix."
                ),
                4: (
                    f"### Escalation: L4 — All-Out\n"
                    f"This is consecutive {trigger_type} #{pua_trigger}. You must exhaust EVERY "
                    "available tool and approach. Try the approach that seems most unlikely. "
                    "Your mental model of this problem is wrong — challenge every assumption. "
                    "If you still cannot fix it, implement a workaround and document exactly "
                    "what's blocking the proper fix in memory/learnings.md."
                ),
            }
            effective_addendum += "\n\n" + pua_escalation.get(pua_level, pua_escalation[4])

        system_prompt = _build_system_prompt(
            state, config,
            initial_direction=initial_direction if is_first_cycle else None,
            wrapping_up=wrapping_up,
            cycle_type_addendum=effective_addendum,
            health_context=heal_health_context,
            timeout_context=last_timeout_context,
        )

        if cycle_type.name == "heal":
            user_message = (
                "The project's build/tests are failing. Fix them before "
                "starting any feature work."
            )
        elif is_first_cycle:
            if is_research:
                user_message = "Start a new research session. Review your tasks and begin investigating."
            else:
                user_message = "Start a new development cycle. What's next?"
        else:
            user_message = _build_continuation_prompt(
                state, config, wrapping_up=wrapping_up,
            )
            # Cycle type instructions are already in the system prompt —
            # no need to duplicate them in the user message.
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
            timeout=effective_timeout,
            stall_timeout=config.stall_timeout,
        )

        # Retry on instant failure — claude CLI sometimes rejects back-to-back
        # invocations (e.g. after micro-replan). If the cycle failed in < 5s
        # with zero output, wait and retry once.
        instant_fail = (
            cycle_result.is_error
            and cycle_result.input_tokens == 0
            and cycle_result.output_tokens == 0
            and cycle_result.duration_seconds < 5
        )
        if instant_fail:
            console.print(
                f"  [yellow]Instant failure detected — retrying after 10s...[/yellow]"
            )
            if cycle_result.output:
                console.print(f"  [dim]Error: {cycle_result.output[:300]}[/dim]")
            time.sleep(10)
            cycle_result = run_cycle(
                user_message=user_message,
                system_prompt=system_prompt,
                model=config.model,
                timeout=effective_timeout,
                stall_timeout=config.stall_timeout,
            )

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
                    # Include error output for diagnosis
                    error_hint = ""
                    if cycle_result.output:
                        error_hint = f": {cycle_result.output[:200]}"
                    summary = f"Cycle terminated abnormally{error_hint}"

        # Independent health check — skip for non-code cycles and research workflow
        non_code_cycles = ("planning", "replan", "spike", "explore",
                           "research", "synthesize")
        if is_research or cycle_type.name in non_code_cycles:
            health = HealthCheckResult(passed=True)
            health.build_ok = None
            health.tests_ok = None
            last_health_context = ""
            console.print("  [dim]Health check skipped (non-code cycle)[/dim]")
        else:
            # Clean up any dirty state left by failed WIP commits or
            # lint-staged hooks before running independent health check
            _cleanup_dirty_state(worktree_dir)
            health = run_health_check(
                build_cmd=config.health_check_build,
                test_cmd=config.health_check_test,
                timeout=config.health_check_timeout,
                cwd=worktree_dir or None,
            )
            last_health_context = get_health_summary(
                health.build_ok, health.tests_ok, health.test_output,
                health.build_output,
                build_cmd=config.health_check_build,
                test_cmd=config.health_check_test,
            )

        # Rollback only on REGRESSION — if baseline was already broken and the
        # cycle didn't make it worse, keep the work.
        has_saved_partial = cycle_result.timeout_type in ("stall", "duration")
        regressed = health_regressed(baseline_health, health)
        if (regressed and config.rollback_on_failure
                and checkpoint.success and not has_saved_partial):
            console.print(
                f"[red]Health REGRESSED after cycle {cycle}. "
                f"Rolling back to {checkpoint.tag}[/red]"
            )
            rollback_to_checkpoint(checkpoint.tag)
            outcome = "failed"
            summary += " (rolled back — health regressed)"
        elif not health.passed and not regressed and cycle_type.name not in non_code_cycles:
            console.print(
                "  [yellow]Health check failed but no regression from baseline "
                "— keeping changes.[/yellow]"
            )

        # If a heal cycle passed health, promote baseline to healthy
        if cycle_type.name == "heal" and health.passed:
            baseline_healthy = True
            baseline_health = health
            consecutive_heal_successes_but_health_fails = 0
            console.print("  [green]Project healed! Resuming normal cycles.[/green]")
        elif cycle_type.name == "heal" and outcome in ("success", "wrapped_up") and not health.passed:
            # Agent says it fixed things but health check still fails —
            # likely a config error (wrong project name, wrong scheme, etc.)
            consecutive_heal_successes_but_health_fails += 1
            if consecutive_heal_successes_but_health_fails >= 2:
                console.print(Panel(
                    "[yellow bold]Heal loop detected:[/yellow bold] Agent reports success "
                    "but health check keeps failing. This is likely a health check "
                    "CONFIG problem, not a code problem.\n"
                    "Disabling health checks for the rest of this session.\n"
                    "Fix .brewin/config.toml and restart.",
                    border_style="yellow",
                ))
                config.health_check_build = None
                config.health_check_test = None
                baseline_healthy = True

        # Agent-mode push: push to agent branch after health check passes
        # This ensures only verified code gets pushed, preventing concurrent
        # sessions from stepping on each other via premature pushes.
        if (config.agent_name and worktree_dir
                and outcome not in ("failed",)
                and cycle_type.name not in non_code_cycles
                and health.passed):
            # Safety: verify we're on an agent branch, never push to main/master
            branch_check = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True,
                cwd=worktree_dir, timeout=10,
            )
            current_branch = branch_check.stdout.strip()
            if current_branch in ("main", "master", ""):
                console.print(
                    f"  [red]Push blocked — on '{current_branch}', not an agent branch.[/red]"
                )
            else:
                push_result = subprocess.run(
                    ["git", "push", "-u", "origin", "HEAD"],
                    capture_output=True, text=True,
                    cwd=worktree_dir, timeout=60,
                )
                if push_result.returncode == 0:
                    console.print("  [green]Pushed agent branch to remote.[/green]")
                else:
                    console.print(
                        f"  [yellow]Agent push failed (non-critical): "
                        f"{push_result.stderr.strip()[-200:]}[/yellow]"
                    )

        last_outcome = outcome

        # Track work cycles for periodic test/cleanup/explore/synthesize insertion
        work_cycle_types = ("deep_work", "quick_fix", "continue_work",
                            "refactor", "debug", "perf", "research")
        if cycle_type.name in work_cycle_types and outcome != "failed":
            work_cycles_since_test += 1
            work_cycles_since_cleanup += 1
            work_cycles_since_explore += 1
            work_cycles_since_synthesize += 1
        if cycle_type.name == "test":
            work_cycles_since_test = 0
        if cycle_type.name == "cleanup":
            work_cycles_since_cleanup = 0
        if cycle_type.name == "explore":
            work_cycles_since_explore = 0
        if cycle_type.name == "synthesize":
            work_cycles_since_synthesize = 0

        # Consecutive failure cap — stop burning cycles on structural failures
        # PUA raises the cap to 6 (pushes through with escalating pressure)
        failure_cap = 6 if config.pua else 3
        if outcome == "failed":
            consecutive_failures += 1
            if consecutive_failures >= failure_cap:
                console.print(
                    f"[red]{failure_cap} consecutive failures — stopping to avoid "
                    "wasting cycles.[/red]"
                )
                break
        else:
            consecutive_failures = 0

        # Consecutive wrapped_up cap — agent says it's done, stop the loop
        if outcome == "wrapped_up":
            consecutive_wrapped_up += 1
            if consecutive_wrapped_up >= 2:
                console.print(
                    "[green]Agent wrapped up twice — session complete.[/green]"
                )
                break
        else:
            consecutive_wrapped_up = 0

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

        # Micro-replan: quick task update after work cycles (not after replan/planning/ship)
        # With PUA enabled, also run micro-replan after failed and pua_pressure cycles
        # to capture failure patterns in memory
        pua_replan_eligible = config.pua and (
            cycle_type.name == "pua_pressure" or outcome == "failed"
        )
        if (config.micro_replan
                and (cycle_type.name in ("deep_work", "quick_fix", "continue_work",
                                         "test", "refactor", "debug", "perf",
                                         "cleanup", "spike", "security_audit",
                                         "explore", "research", "synthesize")
                     or pua_replan_eligible)
                and (outcome != "failed" or pua_replan_eligible)
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

        if _shutdown_requested:
            console.print("[yellow]Shutdown requested — stopping gracefully.[/yellow]")
            break

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


def _get_outstanding_tasks(config: BrewinConfig) -> list[str]:
    """Return unchecked task lines from tasks.md."""
    tasks = _read_file_safe(os.path.join(config.state_dir, "tasks.md"))
    if not tasks:
        return []
    return [line.strip() for line in tasks.splitlines() if line.strip().startswith("- [ ]")]


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

    outstanding = _get_outstanding_tasks(config)
    if outstanding:
        task_list = "\n".join(f"  {t}" for t in outstanding)
        console.print(Panel(
            task_list,
            title="Outstanding Tasks",
            border_style="yellow",
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

    outstanding = _get_outstanding_tasks(config)
    if outstanding:
        lines.append("## Outstanding Tasks")
        lines.append("")
        for t in outstanding:
            lines.append(t)
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


def _show_agent_status(config: BrewinConfig, agent_name: str):
    """Show status for a specific agent."""
    mgr = StateManager(config.state_dir)
    state = mgr.load()

    if state.cycle_count == 0:
        console.print(f"[dim]No session found for agent '{agent_name}'.[/dim]")
        return

    branch = get_agent_branch(agent_name, os.getcwd())
    console.print(Panel(
        f"  Agent:   [magenta]{agent_name}[/magenta]\n"
        f"  Session: {state.session_id}\n"
        f"  Cycles:  {state.cycle_count}\n"
        f"  Branch:  {branch or 'none'}\n"
        f"  Tokens:  {state.total_input_tokens:,}in / {state.total_output_tokens:,}out\n"
        f"  Cost:    ${state.total_cost_usd:.4f}",
        title=f"Agent: {agent_name}",
        border_style="magenta",
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
    parser.add_argument("--agent", default=None,
                        help="Run as a specialized agent (loads profile from .brewin/agents/<name>/)")
    parser.add_argument("--cycle-type", choices=[
                            "planning", "quick_fix", "deep_work", "review", "replan", "heal",
                            "spike", "test", "refactor", "debug", "ship",
                            "security_audit", "perf", "cleanup", "explore",
                            "pua_pressure",
                        ],
                        default=None, help="Force a specific cycle type for all cycles")
    parser.add_argument("--no-rollback", action="store_true",
                        help="Disable automatic rollback on health check failure")
    parser.add_argument("--no-replan", action="store_true",
                        help="Disable micro-replan after each cycle")
    parser.add_argument("--replan-interval", type=int, default=None,
                        help="Insert full replan cycle every N work cycles (0=disabled)")
    parser.add_argument("--stall-timeout", type=int, default=None,
                        help="Seconds with no output before killing a cycle (default: 300)")
    parser.add_argument("--pua", action="store_true",
                        help="Enable PUA pressure cycles on consecutive failures (layers on any workflow)")

    args = parser.parse_args()

    config = load_config(
        agent_name=args.agent,
        time_budget_minutes=args.time,
        autonomy_mode=args.mode,
        model=args.model,
        cycle_type_override=args.cycle_type,
    )

    if args.no_rollback:
        config.rollback_on_failure = False
    if args.no_replan:
        config.micro_replan = False
    if args.pua or args.cycle_type == "pua_pressure":
        config.pua = True
    if args.replan_interval is not None:
        config.replan_interval = args.replan_interval
    if args.stall_timeout is not None:
        config.stall_timeout = args.stall_timeout

    if args.project != ".":
        os.chdir(args.project)

    if args.status:
        if args.agent:
            # List all agents or show specific agent status
            _show_agent_status(config, args.agent)
        else:
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
