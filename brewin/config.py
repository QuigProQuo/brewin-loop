"""
Brewin Loop configuration.
"""

import os
from dataclasses import dataclass
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
    }
    for marker, lang in markers.items():
        if (root / marker).exists():
            return lang
    return "unknown"


def load_config(**overrides) -> BrewinConfig:
    config = BrewinConfig()

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

    for key, val in overrides.items():
        if hasattr(config, key) and val is not None:
            setattr(config, key, val)

    return config
