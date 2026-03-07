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
    """Get recent git activity: last 5 commits + diff stat from last commit."""
    parts = []

    log = _git_output("log", "--oneline", "-5", cwd=cwd)
    if log:
        parts.append(f"Recent commits:\n{log}")

    diff_stat = _git_output("diff", "--stat", "HEAD~1", cwd=cwd)
    if diff_stat:
        parts.append(f"Last commit changes:\n{diff_stat}")

    # Uncommitted changes
    status = _git_output("status", "--short", cwd=cwd)
    if status:
        parts.append(f"Uncommitted changes:\n{status}")

    return "\n\n".join(parts) if parts else "No git context available."


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


def get_health_summary(build_ok: bool | None, tests_ok: bool | None,
                       test_output: str = "") -> str:
    """Format health check results for inclusion in prompts."""
    parts = []

    if build_ok is True:
        parts.append("Build: PASSING")
    elif build_ok is False:
        parts.append("Build: FAILING")

    if tests_ok is True:
        parts.append("Tests: PASSING")
    elif tests_ok is False:
        parts.append("Tests: FAILING")
        if test_output:
            # Include last 15 lines of test output
            lines = test_output.strip().splitlines()[-15:]
            parts.append("Test output (last 15 lines):\n" + "\n".join(lines))

    return "\n".join(parts) if parts else ""
