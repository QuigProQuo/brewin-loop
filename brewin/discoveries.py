"""
Cross-agent discovery sharing via append-only JSONL file.

When running in parallel agent mode, agents can share relevant findings
(architecture patterns, API details, configuration discoveries) without
tight coupling. Discoveries are written to .brewin/shared/discoveries.jsonl
and read by other agents during system prompt construction.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class Discovery:
    timestamp: str
    agent: str
    type: str  # architecture, api, config, dependency, convention, bug
    content: str
    tags: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Discovery":
        return cls(
            timestamp=d["timestamp"],
            agent=d["agent"],
            type=d.get("type", "general"),
            content=d["content"],
            tags=d.get("tags", []),
        )


DISCOVERIES_FILENAME = os.path.join("shared", "discoveries.jsonl")


def _resolve_discoveries_path(brewin_dir: str | None = None) -> str:
    """Resolve the discoveries JSONL path.

    Args:
        brewin_dir: The .brewin directory (project root's .brewin, NOT an agent's
                    state_dir). If None, uses relative .brewin/shared/discoveries.jsonl.
    """
    if brewin_dir:
        return os.path.join(brewin_dir, DISCOVERIES_FILENAME)
    return os.path.join(".brewin", DISCOVERIES_FILENAME)


def brewin_dir_from_state_dir(state_dir: str) -> str:
    """Derive the root .brewin/ directory from an agent's state_dir.

    Agent state_dir is like /path/to/project/.brewin/agents/frontend.
    We need /path/to/project/.brewin/ for the shared discoveries path.
    """
    # state_dir = .../.brewin/agents/<name>  →  go up 2 levels
    return os.path.dirname(os.path.dirname(state_dir))


def write_discovery(
    agent_name: str,
    content: str,
    discovery_type: str = "general",
    tags: list[str] | None = None,
    brewin_dir: str | None = None,
) -> Discovery:
    """Append a discovery to the shared feed.

    Args:
        agent_name: Name of the agent writing the discovery.
        content: The discovery content.
        discovery_type: Category (architecture, api, config, dependency, convention, bug).
        tags: Optional tags for filtering.
        brewin_dir: The root .brewin directory. Required for correct path in worktrees.
    """
    discovery = Discovery(
        timestamp=datetime.now(timezone.utc).isoformat(),
        agent=agent_name,
        type=discovery_type,
        content=content,
        tags=tags or [],
    )
    path = _resolve_discoveries_path(brewin_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(discovery.to_dict()) + "\n")
    return discovery


def read_discoveries(
    exclude_agent: str | None = None,
    max_entries: int = 20,
    max_chars: int = 500,
    brewin_dir: str | None = None,
) -> list[Discovery]:
    """Read recent discoveries, optionally excluding a specific agent's own entries.

    Args:
        exclude_agent: Agent name to exclude (agents skip their own discoveries).
        max_entries: Max number of entries to return.
        max_chars: Max total content chars (prevents prompt bloat).
        brewin_dir: The root .brewin directory. Required for correct path in worktrees.
    """
    path = _resolve_discoveries_path(brewin_dir)
    if not os.path.isfile(path):
        return []

    entries = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = Discovery.from_dict(json.loads(line))
                    if exclude_agent and d.agent == exclude_agent:
                        continue
                    entries.append(d)
                except (json.JSONDecodeError, KeyError):
                    continue
    except (FileNotFoundError, PermissionError):
        return []

    # Take most recent entries, cap total content size
    recent = entries[-max_entries:]
    result = []
    total_chars = 0
    for d in reversed(recent):
        if total_chars + len(d.content) > max_chars:
            break
        result.append(d)
        total_chars += len(d.content)

    result.reverse()
    return result


def format_discoveries(discoveries: list[Discovery]) -> str:
    """Format discoveries for inclusion in system prompt."""
    if not discoveries:
        return ""
    lines = []
    for d in discoveries:
        tags_str = f" [{', '.join(d.tags)}]" if d.tags else ""
        lines.append(f"- **{d.agent}** ({d.type}{tags_str}): {d.content}")
    return "\n".join(lines)
