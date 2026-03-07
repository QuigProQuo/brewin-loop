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

    # Wrap-up: when fewer than this many minutes remain, tell Claude to wrap up
    wrap_up_minutes: int = 5

    # Health checks
    health_check_build: str | None = None
    health_check_test: str | None = None
    health_check_timeout: int = 120
    rollback_on_failure: bool = True

    # Cycle types
    cycle_type_override: str | None = None  # Force a specific cycle type

    # Replanning
    micro_replan: bool = True  # Run a quick task-update call after each work cycle
    replan_interval: int = 4  # Insert a full replan cycle every N work cycles (0 = disabled)
    replan_model: str | None = None  # Model for micro-replan (defaults to main model)

    # Hooks
    pre_cycle_hooks: list[str] = field(default_factory=list)
    post_cycle_hooks: list[str] = field(default_factory=list)
    post_session_hooks: list[str] = field(default_factory=list)

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


def load_config(**overrides) -> BrewinConfig:
    config = BrewinConfig()

    # Load from .brewin/config.toml
    toml_data = _load_toml_config(config.state_dir)

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

    if "cycle_type" in toml_data:
        config.cycle_type_override = toml_data["cycle_type"]

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
