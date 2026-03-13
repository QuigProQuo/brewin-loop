"""
Brewin Loop configuration.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BrewinConfig:
    # Model — CLI alias (sonnet, opus, haiku) or full model ID
    model: str = "sonnet"

    # Time-based control
    time_budget_minutes: int = 60

    # Safety caps
    max_cycles: int = 100

    # Pacing
    sleep_between_cycles: int = 5  # seconds

    # Autonomy
    autonomy_mode: str = "autonomous"  # "autonomous" | "confirm-first"

    # Project files
    mission_file: str = "Mission.md"
    state_dir: str = ".brewin"

    # Agent mode
    agent_name: str | None = None
    worktree_setup: str | None = None  # Shell command to run after worktree creation (e.g., "pnpm install")

    # Wrap-up: when fewer than this many minutes remain, tell Claude to wrap up
    wrap_up_minutes: int = 5

    # Health checks
    health_check_build: str | None = None
    health_check_test: str | None = None
    health_check_timeout: int = 120
    rollback_on_failure: bool = True

    # Cycle types
    cycle_type_override: str | None = None  # Force a specific cycle type
    cycle_timeout: int | None = None  # Optional per-cycle duration limit (seconds)

    # Stall detection — seconds with no output before killing a cycle
    stall_timeout: int = 300  # 5 minutes default

    # Replanning
    micro_replan: bool = True  # Run a quick task-update call after each work cycle
    replan_interval: int = 4  # Insert a full replan cycle every N work cycles (0 = disabled)
    replan_model: str | None = None  # Model for micro-replan (defaults to main model)

    # Hooks
    pre_cycle_hooks: list[str] = field(default_factory=list)
    post_cycle_hooks: list[str] = field(default_factory=list)
    post_session_hooks: list[str] = field(default_factory=list)

    # Workflow — "development" (default) or "research" (no health checks, research cycles)
    workflow: str = "development"

    # PUA — enable PUA (Prompt Underperformance Analyzer) pressure cycles.
    # Layers on top of any workflow. On consecutive failures, triggers escalating
    # pua_pressure cycles instead of stopping. Raises failure cap from 3 to 6.
    pua: bool = False

    # Prompt limits
    max_prompt_chars: int = 15000


def detect_project_type(root: str = ".") -> str:
    root = Path(root)
    markers = {
        "package.json": "node",
        "tsconfig.json": "typescript",
        "pyproject.toml": "python",
        "requirements.txt": "python",
        "go.mod": "go",
        "Cargo.toml": "rust",
        "Gemfile": "ruby",
        "Package.swift": "swift",
    }
    for marker, lang in markers.items():
        if (root / marker).exists():
            return lang
    # Check for .xcodeproj directories (Swift/iOS projects without Package.swift)
    if any(p.suffix == ".xcodeproj" for p in root.iterdir() if p.is_dir()):
        return "swift"
    return "unknown"


def _load_toml_config(state_dir: str = ".brewin") -> dict:
    """Load .brewin/config.toml if it exists."""
    config_path = Path(state_dir) / "config.toml"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base. Override values win for scalars;
    dicts are merged recursively; lists are replaced."""
    merged = base.copy()
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def load_config(agent_name: str | None = None, **overrides) -> BrewinConfig:
    config = BrewinConfig()

    # When running as an agent, state_dir points to the agent's directory
    if agent_name:
        agent_dir = os.path.join(".brewin", "agents", agent_name)
        if not os.path.isdir(agent_dir):
            raise FileNotFoundError(
                f"Agent directory not found: {agent_dir}\n"
                f"Create it with mission.md and tasks.md before running."
            )
        config.state_dir = agent_dir
        config.agent_name = agent_name

    # Load root config, then merge agent-specific config on top
    root_toml = _load_toml_config(".brewin")
    if agent_name:
        agent_toml = _load_toml_config(config.state_dir)
        toml_data = _deep_merge(root_toml, agent_toml)
    else:
        toml_data = root_toml

    # Apply TOML settings
    if "health" in toml_data:
        health = toml_data["health"]
        if "build" in health:
            config.health_check_build = health["build"]
        if "test" in health:
            config.health_check_test = health["test"]
        if "timeout" in health:
            config.health_check_timeout = int(health["timeout"])
        if "rollback_on_failure" in health:
            config.rollback_on_failure = bool(health["rollback_on_failure"])
        if "worktree_setup" in health:
            config.worktree_setup = health["worktree_setup"]

    if "hooks" in toml_data:
        hooks = toml_data["hooks"]
        if "pre_cycle" in hooks:
            config.pre_cycle_hooks = list(hooks["pre_cycle"])
        if "post_cycle" in hooks:
            config.post_cycle_hooks = list(hooks["post_cycle"])
        if "post_session" in hooks:
            config.post_session_hooks = list(hooks["post_session"])

    if "model" in toml_data:
        config.model = toml_data["model"]

    if "workflow" in toml_data:
        config.workflow = toml_data["workflow"]

    if "pua" in toml_data:
        config.pua = bool(toml_data["pua"])

    if "cycle_type" in toml_data:
        config.cycle_type_override = toml_data["cycle_type"]

    if "cycle_timeout" in toml_data:
        config.cycle_timeout = int(toml_data["cycle_timeout"])

    if "stall_timeout" in toml_data:
        config.stall_timeout = int(toml_data["stall_timeout"])

    if "replan" in toml_data:
        replan = toml_data["replan"]
        if "micro_replan" in replan:
            config.micro_replan = bool(replan["micro_replan"])
        if "interval" in replan:
            config.replan_interval = int(replan["interval"])
        if "model" in replan:
            config.replan_model = replan["model"]

    # Apply env vars (override TOML)
    env_map = {
        "BREWIN_MODEL": "model",
        "BREWIN_TIME": "time_budget_minutes",
        "BREWIN_MODE": "autonomy_mode",
        "BREWIN_MAX_CYCLES": "max_cycles",
    }
    for env_key, attr in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            current = getattr(config, attr)
            if isinstance(current, int):
                val = int(val)
            setattr(config, attr, val)

    # Apply CLI overrides (highest priority)
    for key, val in overrides.items():
        if hasattr(config, key) and val is not None:
            setattr(config, key, val)

    return config
