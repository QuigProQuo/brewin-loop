"""
Adaptive cycle types for Brewin Loop.
Different cycle types have different timeouts and prompt instructions.
"""

from dataclasses import dataclass

from brewin.prompts import CYCLE_PROMPTS


@dataclass
class CycleType:
    name: str
    timeout: int | None  # None = no duration limit (stall detection only)
    prompt_addendum: str


CYCLE_TYPES: dict[str, CycleType] = {
    name: CycleType(name=name, timeout=None, prompt_addendum=prompt)
    for name, prompt in CYCLE_PROMPTS.items()
}


def select_cycle_type(
    cycle: int,
    last_outcome: str | None,
    wrapping_up: bool,
    override: str | None = None,
    replan_interval: int = 0,
    consecutive_stalls: int = 0,
    baseline_healthy: bool = True,
    work_cycles_since_test: int = 0,
    work_cycles_since_cleanup: int = 0,
) -> CycleType:
    """Auto-select the appropriate cycle type based on context.

    Args:
        replan_interval: If > 0, insert a replan cycle every N work cycles.
            E.g., replan_interval=4 means cycles 5, 9, 13... are replan cycles.
        consecutive_stalls: Number of consecutive stalled cycles. After 2+,
            escalate to replan instead of continue_work.
        baseline_healthy: Whether the project was healthy at session start.
            If False, the first cycle(s) will be heal cycles until health passes.
        work_cycles_since_test: Number of work cycles since the last test cycle.
            After 5, auto-insert a test cycle.
        work_cycles_since_cleanup: Number of work cycles since the last cleanup.
            After 10, auto-insert a cleanup cycle.
    """
    if override and override in CYCLE_TYPES:
        return CYCLE_TYPES[override]

    # Heal mode takes priority — project must be healthy before real work starts
    if not baseline_healthy:
        return CYCLE_TYPES["heal"]

    if wrapping_up:
        return CYCLE_TYPES["ship"]

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

    # Periodic test cycle: after 5 work cycles without dedicated testing
    if work_cycles_since_test >= 5:
        return CYCLE_TYPES["test"]

    # Periodic cleanup: after 10 work cycles without cleanup
    if work_cycles_since_cleanup >= 10:
        return CYCLE_TYPES["cleanup"]

    return CYCLE_TYPES["deep_work"]
