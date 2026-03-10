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
  context.py       — Git context, project tree, health summaries, structured memory loading
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
- `_build_system_prompt()` in loop.py assembles the full system prompt each cycle by combining: core system prompt + cycle type addendum + mission + tasks + structured memory (4 files) + git context + file change frequency + health results + time remaining
- `MICRO_REPLAN_PROMPT` uses Python `.format()` placeholders (`{focus}`, `{outcome}`, `{memory_architecture}`, `{memory_state}`, etc.) and `{{` for literal braces
- Memory is structured into 4 files in `.brewin/memory/`: architecture.md, decisions.md, state.md, learnings.md
- To add a new cycle type: create a `.md` file in `prompts/cycles/`, then add the name to `select_cycle_type()` logic in cycles.py

## How Cycle Selection Works

`select_cycle_type()` in cycles.py uses a priority chain:

1. **heal** — if baseline health check failed
2. **ship** — if wrapping up (near time limit)
3. **explore** — if agent reported `needs_exploration` outcome
4. **replan** — if 2+ consecutive stalls
5. **continue_work** — if previous cycle stalled/timed out
6. **review** — if previous cycle failed
7. **planning** — first cycle of session
8. **explore** — cycle 2 if no architecture map exists in memory/
9. **replan** — periodic (every N work cycles)
10. **test** — periodic (every 8 work cycles)
11. **explore** — periodic (every 15 work cycles)
12. **cleanup** — periodic (every 10 work cycles)
13. **deep_work** — default

## Workflows

Brewin supports two workflows, set via `workflow` in config.toml:

### `development` (default)
Code-focused: health checks, rollback, git checkpoints, test/cleanup cycles.

### `research`
Investigation-focused: no health checks, no rollback, no git checkpoints.
Uses `research` cycles (with WebSearch/WebFetch) instead of `deep_work`,
and periodic `synthesize` cycles (every 5 research cycles) to consolidate findings.
Reports go to `.brewin/reports/`. Agent config example:

```toml
workflow = "research"

[health]
build = "true"
test = "true"
```

Research cycle selection priority chain:
1. **ship** — wrapping up
2. **replan** — 2+ consecutive stalls, or failed
3. **continue_work** — previous cycle stalled/timed out
4. **planning** — first cycle
5. **explore** — cycle 2 (understand codebase)
6. **replan** — periodic
7. **synthesize** — every 5 research cycles
8. **research** — default

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