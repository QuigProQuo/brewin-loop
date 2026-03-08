"""
Prompt loader for Brewin Loop.

Loads prompt text from markdown files at import time so prompts
are editable without touching Python code.
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def _load_prompt(filename: str) -> str:
    """Load a prompt file from the prompts directory."""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


# Core prompts
BREWIN_SYSTEM_PROMPT = _load_prompt("system.md")
MICRO_REPLAN_PROMPT = _load_prompt("micro_replan.md")

# Cycle-type prompts (auto-discovered from cycles/ directory)
CYCLE_PROMPTS: dict[str, str] = {
    f.stem: f.read_text(encoding="utf-8").strip()
    for f in sorted((_PROMPTS_DIR / "cycles").glob("*.md"))
}
