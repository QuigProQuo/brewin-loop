"""
Adaptive cycle types for Brewin Loop.
Different cycle types have different timeouts and prompt instructions.
"""

from dataclasses import dataclass


@dataclass
class CycleType:
    name: str
    timeout: int  # seconds for claude -p stall timeout
    prompt_addendum: str


CYCLE_TYPES: dict[str, CycleType] = {
    "planning": CycleType(
        name="planning",
        timeout=300,
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
        timeout=300,
        prompt_addendum=(
            "## CYCLE MODE: QUICK FIX\n"
            "This is a quick-fix cycle. Focus on a single small fix, improvement, "
            "or cleanup task. Do NOT start large features or refactors. Commit and "
            "move on."
        ),
    ),
    "deep_work": CycleType(
        name="deep_work",
        timeout=1800,
        prompt_addendum=(
            "## CYCLE MODE: DEEP WORK\n"
            "You have extended time for this cycle. Tackle complex features, "
            "multi-file changes, or deep refactors. Take the time to do it right."
        ),
    ),
    "review": CycleType(
        name="review",
        timeout=600,
        prompt_addendum=(
            "## CYCLE MODE: REVIEW\n"
            "This is an audit cycle. Review code quality, find bugs, update tests, "
            "and clean up technical debt. Do NOT write new features. Record issues "
            "in .brewin/tasks.md."
        ),
    ),
}


def select_cycle_type(
    cycle: int,
    last_outcome: str | None,
    wrapping_up: bool,
    override: str | None = None,
) -> CycleType:
    """Auto-select the appropriate cycle type based on context."""
    if override and override in CYCLE_TYPES:
        return CYCLE_TYPES[override]

    if wrapping_up:
        return CYCLE_TYPES["quick_fix"]

    if last_outcome == "failed":
        return CYCLE_TYPES["review"]

    if cycle == 1:
        return CYCLE_TYPES["planning"]

    return CYCLE_TYPES["deep_work"]
