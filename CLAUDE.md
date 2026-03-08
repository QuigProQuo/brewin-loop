# Brewin Loop

Autonomous, time-based development agent. Wraps `claude -p` in a loop with time budgets, adaptive cycle types, health checks, and persistent memory.

## Architecture

```
brewin/
  loop.py          — Main loop, prompt assembly, CLI entry point
  agent.py         — claude -p subprocess runner, streaming output, stall detection
  cycles.py        — Cycle type definitions + selection algorithm
  config.py        — Config loading from .brewin/config.toml + CLI args
  state.py         — Session state persistence (state.json), cycle logging
  context.py       — Git context, project tree, health summaries
  healthcheck.py   — Independent build/test verification, regression detection
  checkpoint.py    — Git tag checkpoints and rollback
  hooks.py         — Pre/post-cycle hook execution
  worktree.py      — Git worktree isolation for agent mode
  prompts/         — All prompt text as editable markdown files
    __init__.py    — Loader (auto-discovers cycle files at import time)
    system.md      — Core agent instructions (BREWIN_SYSTEM_PROMPT)
    micro_replan.md — Post-cycle task/memory update prompt
    cycles/*.md    — One file per cycle type (filename = cycle name)
```

## How Prompts Work

- Prompts live in `brewin/prompts/` as markdown files, loaded once at import time
- `_build_system_prompt()` in loop.py assembles the full system prompt each cycle by combining: core system prompt + cycle type addendum + mission + tasks + memory + git context + health results + time remaining
- `MICRO_REPLAN_PROMPT` uses Python `.format()` placeholders (`{focus}`, `{outcome}`, etc.) and `{{` for literal braces
- To add a new cycle type: create a `.md` file in `prompts/cycles/`, then add the name to `select_cycle_type()` logic in cycles.py

## How Cycle Selection Works

`select_cycle_type()` in cycles.py uses a priority chain:

1. **heal** — if baseline health check failed
2. **ship** — if wrapping up (near time limit)
3. **replan** — if 2+ consecutive stalls
4. **continue_work** — if previous cycle stalled/timed out
5. **review** — if previous cycle failed
6. **planning** — first cycle of session
7. **replan** — periodic (every N work cycles)
8. **test** — periodic (every 5 work cycles)
9. **cleanup** — periodic (every 10 work cycles)
10. **deep_work** — default

## Key Patterns

- Each cycle is a fresh `claude -p` subprocess (no session continuity — it crashed)
- Context is rebuilt every cycle via system prompt to simulate continuity
- `_read_file_safe()` returns `None` for missing files (used throughout)
- `CycleResult` dataclass captures output, tokens, cost, timeout type, partial diffs
- Atomic state writes via `StateManager` (temp file + rename)
- Watchdog thread in agent.py detects stalls (no output for 5 min)
- Health regression = rollback; baseline already broken = keep changes

## Development

- Python 3.11+, `uv` for dependency management
- Entry point: `brewin` CLI via `brewin.loop:main`
- Only external dependency: `rich` (console output)
- Run directly: `python -m brewin.loop`

## Conventions

- Dataclasses for structured data
- Type hints on all function signatures
- Rich console for all user-facing output
- No classes for orchestration — pure functions with state passed explicitly