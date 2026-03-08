"""
Context gathering for Brewin Loop.
Provides git diff, project tree, and test status for system prompts.
"""

import os
import subprocess
from pathlib import Path


def _git_output(*args: str, cwd: str | None = None, max_chars: int = 2000) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True, text=True,
            cwd=cwd, timeout=15,
        )
        output = result.stdout.strip()
        if len(output) > max_chars:
            output = output[:max_chars] + "\n...(truncated)"
        return output
    except Exception:
        return ""


def get_git_context(cwd: str | None = None) -> str:
    """Get recent git activity: last 8 commits + recent file changes."""
    parts = []

    log = _git_output("log", "--oneline", "-8", cwd=cwd)
    if log:
        parts.append(f"Recent commits:\n{log}")

    diff_stat = _git_output("diff", "--stat", "HEAD~1", cwd=cwd)
    if diff_stat:
        parts.append(f"Last commit changes:\n{diff_stat}")

    # Files changed in last 3 commits (broader awareness)
    recent_files = _git_output("diff", "--name-only", "HEAD~3", cwd=cwd)
    if recent_files:
        parts.append(f"Files changed in last 3 commits:\n{recent_files}")

    # Uncommitted changes
    status = _git_output("status", "--short", cwd=cwd)
    if status:
        parts.append(f"Uncommitted changes:\n{status}")

    return "\n\n".join(parts) if parts else "No git context available."


def get_recently_changed_files(n_commits: int = 10, cwd: str | None = None) -> str:
    """Return files changed in the last N commits with change frequency."""
    raw = _git_output(
        "log", f"-{n_commits}", "--pretty=format:", "--name-only",
        cwd=cwd, max_chars=5000,
    )
    if not raw:
        return ""

    counts: dict[str, int] = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if line:
            counts[line] = counts.get(line, 0) + 1

    if not counts:
        return ""

    # Sort by frequency, take top 15
    sorted_files = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:15]
    lines = [f"  {count}x  {path}" for path, count in sorted_files]
    return f"Most frequently changed files (last {n_commits} commits):\n" + "\n".join(lines)


def get_project_tree(root: str = ".", max_files: int = 100) -> str:
    """Get a file tree of the project, excluding common noise directories."""
    exclude_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".next", ".nuxt", "target", ".brewin",
    }
    exclude_extensions = {".pyc", ".pyo", ".class", ".o", ".so", ".dylib"}

    root_path = Path(root).resolve()
    files = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune excluded directories
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]

        rel_dir = Path(dirpath).relative_to(root_path)
        for f in sorted(filenames):
            if Path(f).suffix in exclude_extensions:
                continue
            if f.startswith("."):
                continue
            rel_path = rel_dir / f
            files.append(str(rel_path))
            if len(files) >= max_files:
                files.append(f"... ({max_files}+ files, truncated)")
                return "\n".join(files)

    return "\n".join(files) if files else "Empty project."


MEMORY_FILES = ("architecture", "decisions", "state", "learnings")


def load_structured_memory(state_dir: str) -> dict[str, str]:
    """Load all memory files from the memory/ directory."""
    memory_dir = os.path.join(state_dir, "memory")
    result = {}
    for name in MEMORY_FILES:
        path = os.path.join(memory_dir, f"{name}.md")
        try:
            with open(path) as f:
                result[name] = f.read().strip()
        except (FileNotFoundError, PermissionError):
            result[name] = ""
    return result


def has_architecture_map(state_dir: str) -> bool:
    """Check if a meaningful architecture map exists."""
    path = os.path.join(state_dir, "memory", "architecture.md")
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 100
    except OSError:
        return False


def get_health_summary(build_ok: bool | None, tests_ok: bool | None,
                       test_output: str = "", build_output: str = "",
                       build_cmd: str | None = None,
                       test_cmd: str | None = None) -> str:
    """Format health check results for inclusion in prompts."""
    parts = []

    if build_cmd:
        parts.append(f"Build command: `{build_cmd}`")
    if test_cmd:
        parts.append(f"Test command: `{test_cmd}`")

    if build_ok is True:
        parts.append("Build: PASSING")
    elif build_ok is False:
        parts.append("Build: FAILING")
        if build_output:
            lines = build_output.strip().splitlines()[-15:]
            parts.append("Build output (last 15 lines):\n" + "\n".join(lines))

    if tests_ok is True:
        parts.append("Tests: PASSING")
    elif tests_ok is False:
        parts.append("Tests: FAILING")
        if test_output:
            # Include last 15 lines of test output
            lines = test_output.strip().splitlines()[-15:]
            parts.append("Test output (last 15 lines):\n" + "\n".join(lines))

    return "\n".join(parts) if parts else ""
