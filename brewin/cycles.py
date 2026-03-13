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
    has_architecture_map: bool = False,
    work_cycles_since_explore: int = 0,
    workflow: str = "development",
    work_cycles_since_synthesize: int = 0,
    consecutive_failures: int = 0,
    pua: bool = False,
) -> CycleType:
    """Auto-select the appropriate cycle type based on context.

    Args:
        replan_interval: If > 0, insert a replan cycle every N work cycles.
            E.g., replan_interval=4 means cycles 5, 9, 13... are replan cycles.
        consecutive_stalls: Number of consecutive stalled cycles. After 2+,
            escalate to replan instead of continue_work.
        consecutive_failures: Number of consecutive failed cycles. In PUA workflow,
            triggers pua_pressure cycles at 2+ instead of stopping at 3.
        baseline_healthy: Whether the project was healthy at session start.
            If False, the first cycle(s) will be heal cycles until health passes.
        work_cycles_since_test: Number of work cycles since the last test cycle.
            After 8, auto-insert a test cycle.
        work_cycles_since_cleanup: Number of work cycles since the last cleanup.
            After 10, auto-insert a cleanup cycle.
        has_architecture_map: Whether a meaningful architecture map exists in
            memory/architecture.md. If False, an explore cycle is triggered early.
        work_cycles_since_explore: Number of work cycles since the last explore.
            After 15, auto-insert an explore cycle to refresh codebase understanding.
        workflow: "development" (default) or "research". Research workflow uses
            research/synthesize cycles instead of deep_work/test.
        work_cycles_since_synthesize: Number of work cycles since the last synthesize
            cycle. After 5, auto-insert a synthesize cycle (research workflow only).
    """
    if override and override in CYCLE_TYPES:
        return CYCLE_TYPES[override]

    if workflow == "research":
        return _select_research_cycle(
            cycle, last_outcome, wrapping_up,
            replan_interval=replan_interval,
            consecutive_stalls=consecutive_stalls,
            work_cycles_since_synthesize=work_cycles_since_synthesize,
            pua=pua,
            consecutive_failures=consecutive_failures,
        )

    # --- Development workflow (default) ---

    # Heal mode takes priority — project must be healthy before real work starts
    if not baseline_healthy:
        return CYCLE_TYPES["heal"]

    if wrapping_up:
        return CYCLE_TYPES["ship"]

    # PUA pressure: escalating debugging on consecutive failures
    if pua and consecutive_failures >= 2 and "pua_pressure" in CYCLE_TYPES:
        return CYCLE_TYPES["pua_pressure"]

    # On-demand explore: agent requested exploration via cycle outcome
    if last_outcome == "needs_exploration":
        return CYCLE_TYPES["explore"]

    if last_outcome in ("stalled", "timed_out"):
        if pua and consecutive_stalls >= 3 and "pua_pressure" in CYCLE_TYPES:
            return CYCLE_TYPES["pua_pressure"]
        if consecutive_stalls >= 2:
            return CYCLE_TYPES["replan"]
        return CYCLE_TYPES["continue_work"]

    if last_outcome == "failed":
        return CYCLE_TYPES["review"]

    if cycle == 1:
        return CYCLE_TYPES["planning"]

    # Explore on cycle 2 if no architecture map exists
    if cycle == 2 and not has_architecture_map:
        return CYCLE_TYPES["explore"]

    # Periodic replan: after every N work cycles (cycle 2 is first work cycle)
    if replan_interval > 0 and cycle > 2:
        # Work cycles start at 2 (cycle 1 is planning)
        work_cycle = cycle - 1
        if work_cycle % replan_interval == 0:
            return CYCLE_TYPES["replan"]

    # Periodic test cycle: after 8 work cycles without dedicated testing
    if work_cycles_since_test >= 8:
        return CYCLE_TYPES["test"]

    # Periodic explore: refresh codebase understanding after 15 work cycles
    if work_cycles_since_explore >= 15:
        return CYCLE_TYPES["explore"]

    # Periodic cleanup: after 10 work cycles without cleanup
    if work_cycles_since_cleanup >= 10:
        return CYCLE_TYPES["cleanup"]

    return CYCLE_TYPES["deep_work"]


def _select_research_cycle(
    cycle: int,
    last_outcome: str | None,
    wrapping_up: bool,
    replan_interval: int = 0,
    consecutive_stalls: int = 0,
    work_cycles_since_synthesize: int = 0,
    pua: bool = False,
    consecutive_failures: int = 0,
) -> CycleType:
    """Cycle selection for the research workflow.

    Research workflow priority chain:
    1. ship — if wrapping up
    2. pua_pressure — if pua enabled and 2+ consecutive failures
    3. replan — if 2+ consecutive stalls
    4. continue_work — if previous cycle stalled/timed out
    5. planning — first cycle
    6. explore — cycle 2 (understand codebase before researching)
    7. replan — periodic (every N research cycles)
    8. synthesize — periodic (every 5 research cycles)
    9. research — default
    """
    if wrapping_up:
        return CYCLE_TYPES["ship"]

    # PUA pressure: escalating debugging on consecutive failures
    if pua and consecutive_failures >= 2 and "pua_pressure" in CYCLE_TYPES:
        return CYCLE_TYPES["pua_pressure"]

    if last_outcome in ("stalled", "timed_out"):
        if pua and consecutive_stalls >= 3 and "pua_pressure" in CYCLE_TYPES:
            return CYCLE_TYPES["pua_pressure"]
        if consecutive_stalls >= 2:
            return CYCLE_TYPES["replan"]
        return CYCLE_TYPES["continue_work"]

    if last_outcome == "failed":
        return CYCLE_TYPES["replan"]

    if cycle == 1:
        return CYCLE_TYPES["planning"]

    if cycle == 2:
        return CYCLE_TYPES["explore"]

    # Periodic replan
    if replan_interval > 0 and cycle > 2:
        work_cycle = cycle - 1
        if work_cycle % replan_interval == 0:
            return CYCLE_TYPES["replan"]

    # Periodic synthesis: consolidate findings every 5 research cycles
    if work_cycles_since_synthesize >= 5:
        return CYCLE_TYPES["synthesize"]

    return CYCLE_TYPES["research"]
