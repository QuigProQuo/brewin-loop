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
  context.py       — Git context, project tree, health summaries, structured memory, discovery loading
  discoveries.py   — Cross-agent discovery sharing via append-only JSONL
  healthcheck.py   — Independent build/test verification, regression detection
  checkpoint.py    — Git tag checkpoints and rollback
  hooks.py         — Pre/post-cycle hook execution
  worktree.py      — Git worktree isolation for agent mode
  prompts/         — All prompt text as editable markdown files
    __init__.py    — Loader (auto-discovers cycle files at import time)
    system.md      — Core agent instructions (BREWIN_SYSTEM_PROMPT)
    micro_replan.md — Post-cycle task/memory update prompt
    pua_overlay.md — PUA behavioral rules injected into all cycles when pua=true
    pua_micro_replan.md — Enhanced micro-replan with failure analysis (pua=true)
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
3. **pua_pressure** — if 2+ consecutive failures (when `pua = true`)
4. **explore** — if agent reported `needs_exploration` outcome
5. **pua_pressure** — if 3+ consecutive stalls (when `pua = true`)
6. **replan** — if 2+ consecutive stalls
7. **continue_work** — if previous cycle stalled/timed out
8. **review** — if previous cycle failed
9. **planning** — first cycle of session
10. **explore** — cycle 2 if no architecture map exists in memory/
11. **replan** — periodic (every N work cycles)
12. **test** — periodic (every 8 work cycles)
13. **explore** — periodic (every 15 work cycles)
14. **cleanup** — periodic (every 10 work cycles)
15. **deep_work** — default

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
2. **pua_pressure** — if 2+ consecutive failures (when `pua = true`)
3. **pua_pressure** — if 3+ consecutive stalls (when `pua = true`)
4. **replan** — 2+ consecutive stalls, or failed
5. **continue_work** — previous cycle stalled/timed out
6. **planning** — first cycle
7. **explore** — cycle 2 (understand codebase)
8. **replan** — periodic
9. **synthesize** — every 5 research cycles
10. **research** — default

### PUA (overlay, not a workflow)

PUA (Prompt Underperformance Analyzer) is a toggle that layers on top of any
workflow. Enable with `pua = true` in config.toml or `--pua` on the CLI.

```toml
workflow = "development"  # or "research" — PUA works with either
pua = true
```

PUA integrates at 4 levels:

1. **System prompt overlay** — Every cycle gets PUA behavioral rules (iron rules,
   anti-patterns, proactivity standards) injected into the system prompt via
   `prompts/pua_overlay.md`. This raises the quality bar for all cycle types.

2. **Pressure cycles** — On 2+ consecutive failures OR 3+ consecutive stalls,
   triggers `pua_pressure` cycles with SEMER methodology and escalating pressure:
   - **L1 (2 failures / 3 stalls)** — Nudge: switch approaches
   - **L2 (3 failures / 4 stalls)** — Investigate: systematic source reading
   - **L3 (4)** — Checklist: 7-point systematic debugging
   - **L4 (5+)** — All-out: exhaust every tool and approach
   Raises failure cap from 3 to 6.

3. **Enhanced micro-replan** — Uses `prompts/pua_micro_replan.md` instead of the
   standard micro-replan. Adds failure analysis, lazy pattern detection, and
   alternative approach suggestions to memory updates.

4. **Failure micro-replan** — Normally micro-replan skips failed cycles. With PUA,
   it runs after failures and pua_pressure cycles to capture failure patterns in
   memory so the next cycle doesn't repeat mistakes.

## Cross-Agent Discovery Sharing

When running in agent mode (parallel via brewin-agent), agents can share findings
with each other through `.brewin/shared/discoveries.jsonl`. This is an append-only
JSONL file at the project root (NOT in the worktree).

**Writing discoveries:** During micro-replan, Claude can emit `DISCOVERY[type|tags]: content`
lines. These are parsed by `_extract_discoveries()` in loop.py and appended to the shared file.

**Reading discoveries:** Each cycle's system prompt includes a `## Discoveries from Other Agents`
section (when in agent mode) with recent discoveries from OTHER agents, capped at 500 chars.

**Path resolution:** Since agents run in worktrees, the discoveries path is resolved from
`config.state_dir` (which is absolute) by walking up to the root `.brewin/` directory via
`brewin_dir_from_state_dir()`.

Discovery types: `architecture`, `api`, `config`, `dependency`, `convention`, `bug`

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