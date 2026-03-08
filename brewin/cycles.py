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
    "spike": CycleType(
        name="spike",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: SPIKE (Research Only)\n"
            "This is a research/investigation cycle. You are exploring approaches, "
            "NOT building features.\n\n"
            "Rules:\n"
            "- Do NOT commit application code changes.\n"
            "- Do NOT modify source files.\n"
            "- You MAY create scratch/prototype files to test ideas, but delete them "
            "before ending the cycle.\n\n"
            "Your job:\n"
            "1. Read relevant code, docs, and dependencies to understand the problem.\n"
            "2. Explore 2-3 possible approaches. Note trade-offs.\n"
            "3. Write your findings to `.brewin/memory.md` — approaches considered, "
            "recommended approach, risks, and key implementation details.\n"
            "4. Update `.brewin/tasks.md` with concrete subtasks based on your "
            "recommended approach.\n\n"
            "The next cycle will use your findings to start building."
        ),
    ),
    "test": CycleType(
        name="test",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: TEST WRITING\n"
            "This cycle is dedicated to improving test coverage. Do NOT write "
            "application/feature code.\n\n"
            "Your job:\n"
            "1. Read existing tests to understand current coverage and patterns.\n"
            "2. Identify gaps: untested functions, missing edge cases, error paths.\n"
            "3. Write tests following the project's existing test conventions.\n"
            "4. Run the full test suite to verify all tests pass (old and new).\n"
            "5. Commit the new tests.\n\n"
            "Focus on high-value coverage: critical paths, complex logic, and "
            "recently changed code. Prefer fewer thorough tests over many shallow ones."
        ),
    ),
    "refactor": CycleType(
        name="refactor",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: REFACTOR\n"
            "This cycle is for behavior-preserving code restructuring ONLY.\n\n"
            "Your job:\n"
            "1. Run the test suite FIRST to establish a passing baseline.\n"
            "2. Make structural improvements: extract functions, rename for clarity, "
            "reduce duplication, simplify complex logic.\n"
            "3. Run the test suite AFTER each significant change.\n"
            "4. If tests break, revert that change and try a smaller scope.\n"
            "5. Commit when tests pass.\n\n"
            "Do NOT add features. Do NOT change behavior. Do NOT fix bugs "
            "(log them in .brewin/tasks.md instead). The test suite is your "
            "proof that behavior is preserved."
        ),
    ),
    "debug": CycleType(
        name="debug",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: DEBUG\n"
            "This cycle is for systematic bug investigation and fixing.\n\n"
            "Follow this structured approach:\n"
            "1. REPRODUCE — Confirm the bug exists. Write a failing test if possible.\n"
            "2. HYPOTHESIZE — Form a theory about the root cause based on symptoms.\n"
            "3. ISOLATE — Narrow down the cause. Add logging, check assumptions, "
            "trace the code path.\n"
            "4. ROOT CAUSE — Identify the exact line(s) causing the issue.\n"
            "5. FIX — Make the minimal change to fix the root cause.\n"
            "6. VERIFY — Run tests, confirm the fix, check for side effects.\n"
            "7. PREVENT — Add a regression test if one doesn't exist.\n\n"
            "Do NOT guess-and-check. Be methodical. Document your findings in "
            "the commit message."
        ),
    ),
    "ship": CycleType(
        name="ship",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: SHIP (End-of-Session Wrap-Up)\n"
            "Time is almost up. This is the final cycle. Focus on a clean handoff.\n\n"
            "Checklist:\n"
            "1. Run the full test suite. Fix any failures.\n"
            "2. Ensure ALL changes are committed. No uncommitted work left behind.\n"
            "3. Review git log for this session — clean up any WIP commit messages.\n"
            "4. Update changelog/CHANGES if the project has one.\n"
            "5. Remove any debug artifacts (print statements, TODO hacks, scratch files).\n"
            "6. Update `.brewin/memory.md` with a clear handoff: what was done, "
            "what's next, any known issues.\n"
            "7. Push if the project uses a remote.\n\n"
            "Do NOT start new features. Ship what you have cleanly."
        ),
    ),
    "security_audit": CycleType(
        name="security_audit",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: SECURITY AUDIT\n"
            "This cycle is for reviewing the codebase for security vulnerabilities.\n\n"
            "Check for:\n"
            "1. **Injection** — SQL injection, command injection, XSS, template injection.\n"
            "2. **Secrets** — Hardcoded API keys, passwords, tokens in source code.\n"
            "3. **Authentication/Authorization** — Missing auth checks, privilege escalation.\n"
            "4. **Input validation** — Unvalidated user input, missing sanitization.\n"
            "5. **Dependencies** — Known vulnerable packages (check lock files).\n"
            "6. **Error handling** — Stack traces or internal details exposed to users.\n"
            "7. **Data exposure** — Sensitive data in logs, responses, or error messages.\n\n"
            "For each issue found:\n"
            "- Fix it if the fix is safe and simple.\n"
            "- Otherwise, log it in `.brewin/tasks.md` under `## Discovered` with "
            "severity (CRITICAL/HIGH/MEDIUM/LOW).\n\n"
            "Do NOT refactor or add features. Security fixes only."
        ),
    ),
    "perf": CycleType(
        name="perf",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: PERFORMANCE\n"
            "This cycle is for profiling and optimizing performance.\n\n"
            "Rules:\n"
            "- MEASURE before optimizing. Never guess at bottlenecks.\n"
            "- BENCHMARK before and after changes to prove improvement.\n"
            "- DOCUMENT what you measured and what improved in the commit message.\n\n"
            "Your job:\n"
            "1. Identify the hot path or performance concern.\n"
            "2. Profile or benchmark the current state.\n"
            "3. Optimize: algorithm improvements, caching, reducing allocations, "
            "batching I/O, eliminating redundant work.\n"
            "4. Benchmark again to verify improvement.\n"
            "5. Run the test suite to ensure correctness.\n"
            "6. Commit with before/after metrics in the commit message.\n\n"
            "Do NOT sacrifice readability for micro-optimizations. Focus on "
            "algorithmic wins and eliminating waste."
        ),
    ),
    "cleanup": CycleType(
        name="cleanup",
        timeout=None,
        prompt_addendum=(
            "## CYCLE MODE: CLEANUP\n"
            "This cycle is for mechanical code hygiene. No behavior changes.\n\n"
            "Your job:\n"
            "1. Remove dead code (unused functions, unreachable branches, commented-out code).\n"
            "2. Fix lint warnings and formatting issues.\n"
            "3. Clean up imports (remove unused, sort/organize).\n"
            "4. Update outdated dependencies if safe (patch/minor versions only).\n"
            "5. Remove temporary files, debug artifacts, stale TODOs.\n"
            "6. Run the test suite to verify nothing broke.\n"
            "7. Commit.\n\n"
            "Do NOT refactor architecture. Do NOT add features. Do NOT fix bugs "
            "(log them instead). Keep changes purely mechanical."
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
