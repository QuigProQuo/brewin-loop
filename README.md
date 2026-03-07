# Brewin Loop

Autonomous, time-based development agent powered by [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Give it a time budget and a direction. It builds, iterates, and improves your project until the clock runs out.

## Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Claude Code Max subscription (runs via `claude -p`, not the API)
- Python 3.11+

## Install

```bash
# From GitHub
uv tool install git+https://github.com/johnpeterquigley/brewin-loop

# Or clone and install locally
git clone https://github.com/johnpeterquigley/brewin-loop.git
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
```

## How It Works

Each **session** has a time budget. Within that budget, Brewin runs **cycles**.

Each cycle is a single `claude -p` call where Claude has full autonomy to:
1. Decide what to build (guided by Mission.md, tasks, and memory)
2. Read and understand the codebase
3. Write code, run tests, fix issues
4. Commit and push

The recommended workflow is **What's Next → Dive Deeper → Implement → Audit → Deploy**, but Claude can skip, reorder, or loop back as needed.

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

### `CLAUDE.md` (optional)
Coding conventions that Brewin will follow. Claude Code reads this automatically.

## State & Memory

All Brewin state lives in `.brewin/` (gitignored by default):

```
.brewin/
├── state.json      # Cycle history and session tracking
├── memory.md       # Persistent knowledge — Brewin reads/updates each cycle
├── tasks.md        # Your task backlog
└── sessions/       # Logs from completed sessions
```

**Memory** (`.brewin/memory.md`) is the key feature — Brewin updates it every cycle with what it built, decisions made, current project state, and priorities. When a new session starts, Brewin reads memory to pick up where it left off.

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--time` | 60 | Time budget in minutes |
| `--mode` | autonomous | `autonomous` or `confirm-first` |
| `--model` | sonnet | Claude model: `sonnet`, `opus`, `haiku`, or full ID |
| `--project` | `.` | Project directory |
| `--resume` | — | Resume previous session |
| `--status` | — | Show last session status |

Environment variables: `BREWIN_MODEL`, `BREWIN_TIME`, `BREWIN_MODE`, `BREWIN_MAX_CYCLES`

## License

MIT
