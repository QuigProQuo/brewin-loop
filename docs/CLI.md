# Brewin Loop CLI Reference

## Quick Start

```bash
# 1. Install
uv tool install git+https://github.com/quigproquo/brewin-loop

# 2. Set up your project
cd your-project
echo "# My Project\n\n## Purpose\nDescribe your project here." > Mission.md

# 3. Run
brewin --time 60 "Build the authentication system"
```

Prerequisites: [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated, Claude Code Max subscription, Python 3.11+.

## Command Reference

```
brewin [OPTIONS] [DIRECTION...]
```

### Positional Arguments

| Argument | Description |
|----------|-------------|
| `DIRECTION` | Optional initial mission/direction for the session. Multiple words are joined. When omitted, Brewin uses existing `Mission.md` and memory to decide what to work on. |

### Options

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--time` | `-t` | int | `60` | Time budget in minutes |
| `--mode` | `-m` | choice | `autonomous` | `autonomous` or `confirm-first` (pause between cycles for approval) |
| `--model` | | string | `sonnet` | Claude model: `sonnet`, `opus`, `haiku`, or a full model ID |
| `--project` | `-p` | path | `.` | Path to project directory to work on |
| `--status` | | flag | | Show last session status and exit |
| `--resume` | | flag | | Resume previous session with additional time budget |
| `--agent` | | string | | Run as specialized agent (loads profile from `.brewin/agents/<name>/`) |
| `--cycle-type` | | choice | auto | Force a specific cycle type for all cycles (see [Cycle Types](#cycle-types)) |
| `--no-rollback` | | flag | | Disable automatic rollback on health check failure |
| `--no-replan` | | flag | | Disable micro-replan (task/memory update) after each cycle |
| `--replan-interval` | | int | `4` | Insert full replan cycle every N work cycles (0 = disabled) |
| `--stall-timeout` | | int | `300` | Seconds with no output before killing a cycle |
| `--pua` | | flag | | Enable PUA pressure cycles on consecutive failures (layers on any workflow) |

### Environment Variables

Override config file values (CLI flags override these):

| Variable | Maps To | Example |
|----------|---------|---------|
| `BREWIN_MODEL` | model | `opus` |
| `BREWIN_TIME` | time_budget_minutes | `120` |
| `BREWIN_MODE` | autonomy_mode | `confirm-first` |
| `BREWIN_MAX_CYCLES` | max_cycles | `50` |

## Project Setup

Set up these files in your target repository before running Brewin.

### `Mission.md` (required)

Tells Brewin what the project is about and where it's heading.

```markdown
# My Project

## Purpose
A real-time collaborative note-taking app for remote teams.

## Goals
- Fast, responsive UI
- Real-time sync between users
- Clean, well-tested codebase
```

### `.brewin/tasks.md` (optional)

Your task backlog. Brewin picks the top unchecked item each cycle.

```markdown
# Tasks

## Priority
- [ ] Add user authentication
- [ ] Build the dashboard page
- [ ] Add export to PDF

## Suggested
- [ ] (Brewin adds suggestions here after completing tasks)
```

### `.brewin/config.toml` (optional)

Per-project configuration. See [Configuration File Reference](#configuration-file-reference).

### `CLAUDE.md` (optional)

Coding conventions. Claude Code reads this automatically.

## Configuration File Reference

Location: `.brewin/config.toml`

```toml
# Top-level settings
model = "sonnet"                # Claude model (sonnet, opus, haiku, or full ID)
workflow = "development"        # "development" or "research"
pua = false                     # Enable PUA pressure (layers on any workflow)
cycle_type = "deep_work"        # Force a cycle type (disables adaptive selection)
cycle_timeout = 600             # Per-cycle duration limit in seconds
stall_timeout = 300             # No-output timeout before killing cycle

# Health checks
[health]
build = "npm run build"         # Build command (auto-detected if omitted)
test = "npm test"               # Test command (auto-detected if omitted)
timeout = 120                   # Health check timeout in seconds
rollback_on_failure = true      # Auto-rollback when tests fail
worktree_setup = "npm install"  # Run after worktree creation (agent mode)

# Lifecycle hooks
[hooks]
pre_cycle = [                   # Run before each cycle
    "echo 'Starting cycle'",
]
post_cycle = [                  # Run after each cycle
    "./scripts/notify.sh",
]
post_session = [                # Run when session ends
    "./scripts/deploy-staging.sh",
]

# Replanning
[replan]
micro_replan = true             # Update tasks/memory after each work cycle
interval = 4                    # Full replan every N work cycles (0 = disabled)
model = "haiku"                 # Model for micro-replan (defaults to main model)
```

### Hook Environment Variables

Hooks receive these environment variables:

| Variable | Description |
|----------|-------------|
| `BREWIN_CYCLE` | Current cycle number |
| `BREWIN_OUTCOME` | Cycle outcome (`success`, `failed`, `stalled`, `timed_out`, `needs_exploration`) |
| `BREWIN_FOCUS` | One-line description of what the cycle worked on |
| `BREWIN_SESSION_ID` | Unique session identifier |
| `BREWIN_TIME_REMAINING` | Minutes remaining in session |

### Auto-Detected Project Types

When `build` and `test` commands aren't specified, Brewin detects them:

| Marker File | Language | Test Command |
|-------------|----------|-------------|
| `package.json` | Node.js | `npm test` |
| `tsconfig.json` | TypeScript | `npm test` |
| `pyproject.toml` | Python | `pytest` |
| `requirements.txt` | Python | `pytest` |
| `go.mod` | Go | `go test ./...` |
| `Cargo.toml` | Rust | `cargo test` |
| `Gemfile` | Ruby | — |
| `Package.swift` | Swift | — |

## Workflows

Set via `workflow` in `.brewin/config.toml`.

### `development` (default)

Standard code development. Health checks, rollback, git checkpoints, periodic test/cleanup cycles.

### `research`

Investigation-focused. No health checks, no rollback, no git checkpoints. Uses `research` cycles (with WebSearch/WebFetch) instead of `deep_work`, and periodic `synthesize` cycles to consolidate findings. Reports saved to `.brewin/reports/`.

```toml
workflow = "research"

[health]
build = "true"    # Disable health checks
test = "true"
```

### PUA (overlay)

PUA (Prompt Underperformance Analyzer) is not a workflow — it's a toggle that layers on top of any workflow. Enable with `pua = true` in config or `--pua` on the CLI.

When enabled, PUA integrates at 4 levels: system prompt overlay on all cycles, escalating pressure cycles on consecutive failures/stalls, enhanced micro-replan with failure analysis, and micro-replan after failed cycles. Raises the failure cap from 3 to 6.

```toml
workflow = "research"   # works with any workflow
pua = true
```

See [PUA Pressure Cycles](#pua-pressure-cycles) for details.

## Cycle Types

### Auto-Selection Priority Chain (Development Workflow)

| Priority | Type | Trigger |
|----------|------|---------|
| 1 | `heal` | Build/tests failing at baseline |
| 2 | `ship` | Near time limit (wrap up cleanly) |
| 3 | `pua_pressure` | 2+ consecutive failures (when PUA enabled) |
| 4 | `explore` | Agent reported `needs_exploration` |
| 5 | `pua_pressure` | 3+ consecutive stalls (when PUA enabled) |
| 6 | `replan` | 2+ consecutive stalls |
| 7 | `continue_work` | After a stall or timeout |
| 8 | `review` | After a failed cycle |
| 9 | `planning` | First cycle of session |
| 10 | `explore` | Cycle 2 if no architecture map exists |
| 11 | `replan` | Periodic (every N work cycles) |
| 12 | `test` | Every 8 work cycles |
| 13 | `explore` | Every 15 work cycles |
| 14 | `cleanup` | Every 10 work cycles |
| 15 | `deep_work` | Default |

### Auto-Selection Priority Chain (Research Workflow)

| Priority | Type | Trigger |
|----------|------|---------|
| 1 | `ship` | Wrapping up |
| 2 | `pua_pressure` | 2+ consecutive failures (when PUA enabled) |
| 3 | `pua_pressure` | 3+ consecutive stalls (when PUA enabled) |
| 4 | `replan` | 2+ consecutive stalls, or failed |
| 5 | `continue_work` | Previous cycle stalled/timed out |
| 6 | `planning` | First cycle |
| 7 | `explore` | Cycle 2 (understand codebase) |
| 8 | `replan` | Periodic |
| 9 | `synthesize` | Every 5 research cycles |
| 10 | `research` | Default |

### All Cycle Types

| Type | Purpose | Auto-Selected? |
|------|---------|----------------|
| `planning` | Session startup — read project, set priorities | Yes (cycle 1) |
| `deep_work` | Main implementation work — build features, solve problems | Yes (default) |
| `quick_fix` | Single small fix, commit, move on | Manual only |
| `review` | Code/design review after failures | Yes (after failed cycle) |
| `replan` | Task/strategy reassessment | Yes (periodic + after stalls) |
| `heal` | Fix broken builds/tests | Yes (when baseline unhealthy) |
| `spike` | Research/investigation — no code committed | Manual only |
| `test` | Dedicated testing cycle | Yes (periodic) |
| `refactor` | Behavior-preserving restructuring only | Manual only |
| `debug` | Systematic bug investigation | Manual only |
| `ship` | Wrap up session cleanly | Yes (near time limit) |
| `security_audit` | Vulnerability review | Manual only |
| `perf` | Profile, benchmark, optimize | Manual only |
| `cleanup` | Code cleanup and dead code removal | Yes (periodic) |
| `explore` | Codebase exploration and architecture mapping | Yes (periodic + on demand) |
| `continue_work` | Resume after stall/timeout with context from interrupted cycle | Yes (after stall) |
| `research` | External + internal investigation (research workflow) | Yes (research default) |
| `synthesize` | Consolidate research findings (research workflow) | Yes (research periodic) |
| `pua_pressure` | Escalating systematic debugging (when PUA enabled) | Yes (on consecutive failures/stalls) |

### PUA Pressure Cycles

When `pua = true` is enabled, consecutive failures or stalls trigger escalating pressure levels instead of stopping the session:

| Consecutive Failures/Stalls | Level | Approach |
|-----------------------------|-------|----------|
| 2 failures / 3 stalls | L1 — Nudge | Switch approaches fundamentally, try different angle |
| 3 failures / 4 stalls | L2 — Investigate | Systematic source code reading, search for similar issues |
| 4 | L3 — Checklist | Execute 7-point systematic debugging checklist |
| 5+ | L4 — All-out | Exhaust every available tool and approach |

PUA also integrates beyond pressure cycles:
- **System prompt overlay** — Every cycle gets PUA behavioral rules (iron rules, anti-patterns, proactivity standards)
- **Enhanced micro-replan** — Adds failure analysis, lazy pattern detection, alternative approach suggestions
- **Failure micro-replan** — Runs after failed cycles (normally skipped) to capture failure patterns in memory

The session stops after 6 consecutive failures (vs 3 without PUA).

## Agent Mode

Run specialized agents with isolated worktrees and separate state.

### Setup

```
.brewin/agents/<name>/
├── config.toml     # Agent-specific config (merged on top of root config)
├── mission.md      # Agent-specific mission
├── tasks.md        # Agent-specific backlog
└── memory/         # Agent-specific memory files
```

### Usage

```bash
# Run an agent
brewin --time 60 --agent frontend "Update component styles"

# Check agent status
brewin --status --agent frontend
```

Agent mode creates a git worktree at `.brewin/worktrees/<name>/` so the agent works on an isolated copy. Config is deep-merged: root `.brewin/config.toml` + agent-specific `config.toml`.

## Usage Examples

```bash
# Basic: 2-hour session with direction
brewin --time 120 "Build a REST API with user authentication"

# Fully autonomous, 1 hour, default settings
brewin --time 60

# Confirm between cycles (good for learning how Brewin works)
brewin --time 60 --mode confirm-first

# Use Opus for harder problems
brewin --time 60 --model opus "Refactor the database layer"

# Resume a previous session with 30 more minutes
brewin --resume --time 30

# Check what happened in the last session
brewin --status

# Work on a project in a different directory
brewin --time 60 --project /path/to/repo "Add caching"

# Force a specific cycle type (skip adaptive selection)
brewin --time 60 --cycle-type deep_work "Build the dashboard"

# Research workflow — investigate, don't code
brewin --time 60  # (with workflow = "research" in config.toml)

# PUA — push through failures with escalating pressure
brewin --time 120 --pua "Fix the flaky auth tests"

# PUA with research workflow
brewin --time 60 --pua  # (with workflow = "research" in config.toml)

# Disable rollback (keep changes even if tests break)
brewin --time 60 --no-rollback

# Disable micro-replan (no task/memory updates between cycles)
brewin --time 60 --no-replan

# Shorter stall timeout (kill stuck cycles faster)
brewin --time 60 --stall-timeout 120

# Full replan every 2 work cycles instead of default 4
brewin --time 60 --replan-interval 2

# Agent mode
brewin --time 60 --agent frontend "Update component styles"

# Using environment variables
BREWIN_MODEL=opus BREWIN_TIME=90 brewin "Your mission here"
```

## State & Memory

All Brewin state lives in `.brewin/` (gitignore this directory):

```
.brewin/
├── state.json              # Session state: cycle history, tokens, cost
├── config.toml             # Project configuration
├── tasks.md                # Task backlog (user-managed + Brewin updates)
├── memory/
│   ├── architecture.md     # Codebase structure, key files, patterns
│   ├── decisions.md        # Design decisions and rationale
│   ├── state.md            # Current progress, what works/broken/next
│   └── learnings.md        # Gotchas, env quirks, debugging tips
├── sessions/               # Logs from completed sessions
├── reports/                # Research workflow reports
├── worktrees/              # Agent worktree directories
└── agents/                 # Agent profiles
    └── <name>/
        ├── config.toml
        ├── mission.md
        ├── tasks.md
        └── memory/
```

### Memory Files

Memory is the key continuity mechanism. Brewin reads these at the start of every cycle and updates them at the end:

| File | Purpose | Line Cap |
|------|---------|----------|
| `architecture.md` | Codebase map: key files, entry points, data flow, frameworks | ~100 |
| `decisions.md` | Design decisions and rationale, rejected alternatives | ~50 |
| `state.md` | Current status: what works, what's broken, what's next | ~50 |
| `learnings.md` | Gotchas, env quirks, things that don't work | ~50 |

### Session Continuity

- **Within a session:** Each cycle is a fresh `claude -p` call. Context is rebuilt via the system prompt (mission + tasks + memory + git context).
- **Across sessions:** Memory files persist between sessions. Use `--resume` to continue with additional time.

### Token & Cost Tracking

Every cycle tracks input/output tokens and estimated cost. View with `brewin --status`.

## Graceful Shutdown

Press `Ctrl+C` (SIGINT) or send SIGTERM. Brewin finishes the current cycle, saves state, and exits cleanly. Press `Ctrl+C` again to force-quit.
