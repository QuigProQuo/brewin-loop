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

Do NOT write application code. Only update the tasks and memory files in the state directory.

End with:
```json
{{"cycle_focus": "micro-replan", "cycle_outcome": "success", "cycle_summary": "<what you updated>"}}
```