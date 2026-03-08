"""
Adaptive cycle types for Brewin Loop.
Different cycle types have different timeouts and prompt instructions.
"""

from dataclasses import dataclass


@dataclass
class CycleType:
    name: str
    timeout: int | None  # None = no duration limit (stall detection only)
    prompt_addendum: str


CYCLE_TYPES: dict[str, CycleType] = {
    "planning": CycleType(
        name="planning",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: PLANNING\n"
            "This is a planning cycle. Analyze the project, understand the current "
            "state, break down the next major task into subtasks, and update "
            ".brewin/tasks.md. Do NOT write application code. Focus on understanding "
            "and planning."
        ),
    ),
    "quick_fix": CycleType(
        name="quick_fix",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: QUICK FIX\n"
            "This is a quick-fix cycle. Focus on a single small fix, improvement, "
            "or cleanup task. Do NOT start large features or refactors. Commit and "
            "move on."
        ),
    ),
    "deep_work": CycleType(
        name="deep_work",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: DEEP WORK\n"
            "Tackle complex features, multi-file changes, or deep refactors. "
            "Take the time to do it right."
        ),
    ),
    "review": CycleType(
        name="review",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: REVIEW\n"
            "This is an audit cycle. Review code quality, find bugs, update tests, "
            "and clean up technical debt. Do NOT write new features. Record issues "
            "in .brewin/tasks.md."
        ),
    ),
    "replan": CycleType(
        name="replan",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: REPLAN\n"
            "This is a replanning cycle. Do NOT write application code.\n\n"
            "Your job:\n"
            "1. Read `.brewin/tasks.md`, `.brewin/memory.md`, and recent git history.\n"
            "2. Assess what's been accomplished vs what remains.\n"
            "3. Break down the next 2-3 priority tasks into concrete subtasks.\n"
            "4. Flag any blockers or dependencies you've discovered.\n"
            "5. Reprioritize `## Suggested` and `## Discovered` items if needed.\n"
            "6. Update `.brewin/memory.md` with current project state and priorities.\n"
            "7. If tasks are vague, make them specific and actionable.\n\n"
            "Keep the user's original priority order but enrich their tasks with "
            "subtask breakdowns. Move completed suggestions into the main task list "
            "if they're high-value."
        ),
    ),
    "heal": CycleType(
        name="heal",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: HEAL (Fix Broken Baseline)\n"
            "The project's build or tests are ALREADY FAILING before you start.\n"
            "Your ONLY job is to get the project back to a healthy state.\n\n"
            "1. Read the health check output below carefully.\n"
            "2. Diagnose why the build/tests are failing.\n"
            "3. If the failure is a CONFIG PROBLEM (wrong file paths, wrong project "
            "names, wrong scheme names in `.brewin/config.toml`), fix the config "
            "file. For example, if the build command references a `.xcodeproj` or "
            "scheme that doesn't exist, find the correct project file and update "
            "`.brewin/config.toml` accordingly.\n"
            "4. If the failure is a CODE PROBLEM, fix it with minimal, targeted changes.\n"
            "5. Run the build/tests yourself to verify they pass.\n"
            "6. Commit the fix.\n\n"
            "The health check commands are defined in `.brewin/config.toml` under "
            "`[health]`. You CAN and SHOULD edit this file if the commands are wrong.\n\n"
            "Do NOT start feature work. Do NOT refactor. Just heal the project."
        ),
    ),
    "continue_work": CycleType(
        name="continue_work",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: CONTINUE INTERRUPTED WORK\n"
            "The previous cycle stalled or was interrupted. Partial changes were "
            "auto-saved as a WIP commit.\n\n"
            "Your job:\n"
            "1. Review the partial work details below.\n"
            "2. If MOSTLY COMPLETE: finish, test, and commit properly.\n"
            "3. If BROKEN or INCOHERENT: revert and decompose into smaller tasks "
            "in .brewin/tasks.md.\n"
            "4. Do NOT just retry the same approach that stalled."
        ),
    ),
}


def select_cycle_type(
    cycle: int,
    last_outcome: str | None,
    wrapping_up: bool,
    override: str | None = None,
    replan_interval: int = 0,
    consecutive_stalls: int = 0,
    baseline_healthy: bool = True,
) -> CycleType:
    """Auto-select the appropriate cycle type based on context.

    Args:
        replan_interval: If > 0, insert a replan cycle every N work cycles.
            E.g., replan_interval=4 means cycles 5, 9, 13... are replan cycles.
        consecutive_stalls: Number of consecutive stalled cycles. After 2+,
            escalate to replan instead of continue_work.
        baseline_healthy: Whether the project was healthy at session start.
            If False, the first cycle(s) will be heal cycles until health passes.
    """
    if override and override in CYCLE_TYPES:
        return CYCLE_TYPES[override]

    # Heal mode takes priority — project must be healthy before real work starts
    if not baseline_healthy:
        return CYCLE_TYPES["heal"]

    if wrapping_up:
        return CYCLE_TYPES["quick_fix"]

    if last_outcome in ("stalled", "timed_out"):
        if consecutive_stalls >= 2:
            return CYCLE_TYPES["replan"]
        return CYCLE_TYPES["continue_work"]

    if last_outcome == "failed":
        return CYCLE_TYPES["review"]

    if cycle == 1:
        return CYCLE_TYPES["planning"]

    # Periodic replan: after every N work cycles (cycle 2 is first work cycle)
    if replan_interval > 0 and cycle > 2:
        # Work cycles start at 2 (cycle 1 is planning)
        work_cycle = cycle - 1
        if work_cycle % replan_interval == 0:
            return CYCLE_TYPES["replan"]

    return CYCLE_TYPES["deep_work"]
