"""
Brewin state manager. Persisted to .brewin/state.json.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class BrewinState:
    session_id: str = ""
    claude_session_id: str = ""  # Claude CLI session UUID for continuity
    project_root: str = ""
    start_time: float = 0.0
    cycle_count: int = 0
    cycle_log: list[dict] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0

    def elapsed_minutes(self) -> float:
        if self.start_time == 0:
            return 0.0
        return (time.time() - self.start_time) / 60.0

    def time_remaining_minutes(self, budget: int) -> float:
        return max(0.0, budget - self.elapsed_minutes())

    def is_time_up(self, budget: int) -> bool:
        return self.elapsed_minutes() >= budget

    def is_wrapping_up(self, budget: int, wrap_up: int = 5) -> bool:
        return self.time_remaining_minutes(budget) < wrap_up

    def log_cycle(self, focus: str, outcome: str, summary: str = "",
                  duration: float = 0.0, input_tokens: int = 0,
                  output_tokens: int = 0, cost_usd: float = 0.0):
        self.cycle_count += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost_usd
        self.cycle_log.append({
            "cycle": self.cycle_count,
            "focus": focus,
            "outcome": outcome,
            "summary": summary,
            "duration_seconds": duration,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_history_summary(self) -> str:
        if not self.cycle_log:
            return "No cycles completed yet — this is the first one."
        lines = []
        for e in self.cycle_log[-10:]:
            status = "+" if e["outcome"] == "success" else "x"
            tokens = f"{e.get('input_tokens', 0):,}in/{e.get('output_tokens', 0):,}out"
            line = f"  {status} Cycle {e['cycle']}: {e['focus']} ({e['outcome']}) [{tokens}]"
            if e.get("summary"):
                line += f"\n    {e['summary']}"
            lines.append(line)
        return "\n".join(lines)

    def format_time_remaining(self, budget: int) -> str:
        remaining = self.time_remaining_minutes(budget)
        if remaining >= 60:
            return f"{int(remaining // 60)}h {int(remaining % 60)}m"
        return f"{int(remaining)}m"


class StateManager:
    def __init__(self, state_dir: str = ".brewin"):
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "state.json"

    def load(self) -> BrewinState:
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                return BrewinState(**{
                    k: v for k, v in data.items()
                    if k in BrewinState.__dataclass_fields__
                })
            except (json.JSONDecodeError, TypeError):
                pass
        return BrewinState()

    def save(self, state: BrewinState):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(asdict(state), f, indent=2)

    def reset(self) -> BrewinState:
        state = BrewinState()
        self.save(state)
        return state
