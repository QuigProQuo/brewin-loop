You just completed a development cycle. Review what happened and update the task backlog.

## What Just Happened
Cycle focus: {focus}
Cycle outcome: {outcome}
Cycle summary: {summary}

## Current Tasks
{tasks}

## Current Memory

### Architecture (memory/architecture.md)
{memory_architecture}

### Decisions (memory/decisions.md)
{memory_decisions}

### State (memory/state.md)
{memory_state}

### Learnings (memory/learnings.md)
{memory_learnings}

## Your Job (Be Quick)

1. If the completed task isn't marked `[x]` yet, mark it done.
2. If you partially completed something, update its status note.
3. If the next priority task is complex, add 2-4 subtasks beneath it.
4. If you discovered blockers, add `(BLOCKED: reason)` to affected tasks.
5. Add any discovered issues under `## Discovered`.
6. Update `.brewin/memory/state.md` with current project status.
7. If the cycle discovered architectural patterns or key files, update `memory/architecture.md`.
8. If a design decision was made, append to `memory/decisions.md`.
9. If a gotcha was discovered, append to `memory/learnings.md`.

## PUA Quality Review

Additionally, evaluate this cycle for underperformance patterns:

10. **If the cycle failed or stalled:** Write a brief failure analysis in `memory/learnings.md`:
    - What was attempted and why it failed
    - What approaches have NOT been tried yet
    - What assumptions might be wrong
    This analysis is critical for the next cycle to avoid repeating the same mistakes.

11. **Check for lazy patterns:** Did this cycle show any of these?
    - Retried the same approach without changing strategy
    - Blamed the environment without verifying
    - Had tools available but didn't use them
    - Did busywork instead of tackling the real problem
    If so, note it in `memory/state.md` so the next cycle can course-correct.

12. **Suggest alternative approaches:** If the current task is stuck, add 2-3
    structurally different approaches as subtasks under the current task.

Do NOT write application code. Only update the tasks and memory files in the state directory.

End with:
```json
{{"cycle_focus": "micro-replan", "cycle_outcome": "success", "cycle_summary": "<what you updated>"}}
```