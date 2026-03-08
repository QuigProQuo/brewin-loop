# Brewin Loop

Autonomous, time-based development agent powered by [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Give it a time budget and a direction. It builds, iterates, and improves your project until the clock runs out.

## Brewin Ecosystem

Brewin Loop works standalone as a fully autonomous dev agent. It's also the execution engine for [Brewin Agent](https://github.com/quigproquo/brewin-agent), an intelligent orchestrator that uses Claude Haiku to reason about what cycles to run.

```
Standalone:    You → brewin (loop) → claude -p (Sonnet/Opus)
With Agent:    You → brewin-agent (Haiku reasoning) → brewin (loop) → claude -p (Sonnet/Opus)
```

| | Brewin Loop | Brewin Agent |
|---|---|---|
| **Decides what to do** | Fixed priority chain | Haiku reasons about context |
| **Handles failure** | Retry, then replan, then stop | Reasons about *why*, tries different approach |
| **Context depth** | memory files rewritten each cycle | Agent SDK conversation + persistent journal |
| **Knows when done** | Runs until time expires | Can stop early when tasks complete |
| **Cost overhead** | None | Minimal (Haiku reasoning between cycles) |

## Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Claude Code Max subscription (runs via `claude -p`, not the API)
- Python 3.11+

## Install

```bash
# From GitHub
uv tool install git+https://github.com/quigproquo/brewin-loop

# Or clone and install locally
git clone https://github.com/quigproquo/brewin-loop.git
cd brewin-loop
uv tool install .
```

## Usage

```bash
# Run for 2 hours with initial direction
brewin --time 120 "Build a REST API with user authentication"

# Run for 1 hour, fully autonomous
brewin --time 60

# Confirm between cycles
brewin --time 60 --mode confirm-first

# Resume a previous session with more time
brewin --resume --time 30

# Check status of last session
brewin --status

# Use a specific model
brewin --time 60 --model opus "Refactor the database layer"

# Run against a different project directory
brewin --time 60 --project /path/to/repo "Add caching"

# Force a specific cycle type
brewin --time 60 --cycle-type deep_work "Build the dashboard"

# Disable automatic rollback on test failures
brewin --time 60 --no-rollback
```

## How It Works

Each **session** has a time budget. Within that budget, Brewin runs **cycles**.

Each cycle is a single `claude -p` call where Claude has full autonomy to:
1. Decide what to build (guided by Mission.md, tasks, and memory)
2. Read and understand the codebase
3. Write code, run tests, fix issues
4. Commit and push

### Session Continuity

Cycles within a session share a Claude CLI session ID, so cycle 2+ carries the full conversation history from cycle 1. This eliminates cold-start overhead — Claude doesn't re-read the codebase every cycle.

### Streaming Output

Brewin streams Claude's output in real-time via `stream-json`. You see tool calls and progress as they happen instead of waiting for each cycle to complete.

### Adaptive Cycle Types

Brewin automatically selects the right cycle type based on context. The selection follows a priority chain — the first matching condition wins:

| Priority | Type | Trigger |
|----------|------|---------|
| 1 | `heal` | Build/tests failing at baseline |
| 2 | `ship` | Near time limit — wrap up cleanly |
| 3 | `replan` | 2+ consecutive stalls |
| 4 | `continue_work` | After a stall or timeout |
| 5 | `review` | After a failed cycle |
| 6 | `planning` | First cycle of a new session |
| 7 | `replan` | Periodic (every N work cycles, configurable) |
| 8 | `test` | Every 5 work cycles |
| 9 | `cleanup` | Every 10 work cycles |
| 10 | `deep_work` | Default — most cycles are this |

Additional cycle types available via `--cycle-type`:

| Type | Purpose |
|------|---------|
| `quick_fix` | Single small fix, commit, move on |
| `refactor` | Behavior-preserving restructuring only |
| `debug` | Systematic bug investigation |
| `spike` | Research/investigation — no code committed |
| `security_audit` | Vulnerability review |
| `perf` | Profile, benchmark, optimize |

Each cycle type has its own prompt that scopes and constrains Claude's behavior — a `heal` cycle won't start features, a `deep_work` cycle won't do code reviews, a `spike` cycle won't commit application code.

### Git Checkpoints & Rollback

Before each cycle, Brewin creates a git tag checkpoint. If the independent health check fails after a cycle, Brewin automatically rolls back to the checkpoint. Disable with `--no-rollback`.

### Independent Health Checks

After each cycle, Brewin independently runs your project's build and test commands — it doesn't trust Claude's self-reported outcome. Commands are auto-detected based on project type (pytest, npm test, cargo test, go test) or configurable via `.brewin/config.toml`.

### Token & Cost Tracking

Every cycle tracks input/output tokens and estimated cost. The session summary shows per-cycle and aggregate totals.

## Project Setup

In your target repository, create these files:

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
Per-project configuration for health checks, hooks, and more.

```toml
[health]
build = "npm run build"
test = "npm test"
timeout = 120
rollback_on_failure = true

[hooks]
pre_cycle = ["echo 'Starting cycle'"]
post_cycle = ["./scripts/notify.sh"]
post_session = ["./scripts/deploy-staging.sh"]
```

### `CLAUDE.md` (optional)
Coding conventions that Brewin will follow. Claude Code reads this automatically.

## State & Memory

All Brewin state lives in `.brewin/` (gitignored by default):

```
.brewin/
├── state.json      # Cycle history and session tracking
├── memory.md       # Persistent knowledge — Brewin reads/updates each cycle
├── tasks.md        # Your task backlog
├── config.toml     # Project configuration (health checks, hooks)
└── sessions/       # Logs from completed sessions
```

**Memory** (`.brewin/memory.md`) is the key feature — Brewin updates it every cycle with what it built, decisions made, current project state, and priorities. When a new session starts, Brewin reads memory to pick up where it left off.

## Hooks

Hooks run shell commands at key points in the Brewin lifecycle. Configure in `.brewin/config.toml`:

- **pre_cycle** — Before each cycle starts
- **post_cycle** — After each cycle completes
- **post_session** — After the session ends

Hook commands receive environment variables: `BREWIN_CYCLE`, `BREWIN_OUTCOME`, `BREWIN_FOCUS`, `BREWIN_SESSION_ID`, `BREWIN_TIME_REMAINING`.

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--time` | 60 | Time budget in minutes |
| `--mode` | autonomous | `autonomous` or `confirm-first` |
| `--model` | sonnet | Claude model: `sonnet`, `opus`, `haiku`, or full ID |
| `--project` | `.` | Project directory |
| `--resume` | — | Resume previous session |
| `--status` | — | Show last session status |
| `--cycle-type` | auto | Force a cycle type (any from the tables above) |
| `--no-rollback` | — | Disable automatic rollback on health check failure |

Environment variables: `BREWIN_MODEL`, `BREWIN_TIME`, `BREWIN_MODE`, `BREWIN_MAX_CYCLES`

## License

MIT
