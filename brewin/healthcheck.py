"""
Independent health checks for Brewin Loop.
Verifies the project builds and tests pass after each cycle.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

console = Console()


@dataclass
class HealthCheckResult:
    passed: bool
    build_ok: bool | None = None  # None = no build command configured
    tests_ok: bool | None = None  # None = no test command configured
    build_output: str = ""
    test_output: str = ""
    details: str = ""


def _run_command(cmd: str, cwd: str | None = None,
                 timeout: int = 120) -> tuple[bool, str]:
    """Run a shell command, return (success, truncated_output).
    Treats pytest exit code 5 (no tests collected) as success."""
    try:
        result = subprocess.run(
            cmd, shell=True,
            capture_output=True, text=True,
            cwd=cwd, timeout=timeout,
        )
        output = result.stdout + result.stderr
        # Truncate to last 30 lines
        lines = output.strip().splitlines()
        if len(lines) > 30:
            output = "\n".join(["...(truncated)"] + lines[-30:])
        # pytest exit code 5 = "no tests collected" — not a real failure
        success = result.returncode == 0 or (
            "pytest" in cmd and result.returncode == 5
        )
        return success, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"(timed out after {timeout}s)"
    except Exception as e:
        return False, f"(error: {e})"


def detect_test_command(root: str = ".") -> str | None:
    """Auto-detect the test command based on project files."""
    root = Path(root)

    # Python
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
            return "python -m pytest --tb=short -q"
        return "python -m unittest discover -s tests"

    # Node/TypeScript
    if (root / "package.json").exists():
        import json
        try:
            pkg = json.loads((root / "package.json").read_text())
            if pkg.get("scripts", {}).get("test"):
                return "npm test"
        except (json.JSONDecodeError, OSError):
            pass

    # Rust
    if (root / "Cargo.toml").exists():
        return "cargo test"

    # Go
    if (root / "go.mod").exists():
        return "go test ./..."

    return None


def detect_build_command(root: str = ".") -> str | None:
    """Auto-detect the build command based on project files."""
    root = Path(root)

    if (root / "package.json").exists():
        import json
        try:
            pkg = json.loads((root / "package.json").read_text())
            if pkg.get("scripts", {}).get("build"):
                return "npm run build"
        except (json.JSONDecodeError, OSError):
            pass

    if (root / "Cargo.toml").exists():
        return "cargo build"

    if (root / "go.mod").exists():
        return "go build ./..."

    return None


def is_likely_config_error(result: HealthCheckResult) -> bool:
    """Detect if a health check failure is likely a config problem, not broken code.

    Heuristics: output contains path-related error patterns indicating missing
    files, directories, or commands rather than actual build/test failures.
    """
    error_patterns = [
        "no such file", "not found", "does not exist",
        "unable to locate", "command not found",
        "no such directory", "cannot find",
    ]
    for output in (result.build_output, result.test_output):
        lower = output.lower()
        if any(pat in lower for pat in error_patterns):
            return True
    return False


def health_regressed(baseline: HealthCheckResult, current: HealthCheckResult) -> bool:
    """Return True if current health is worse than baseline.

    Rules:
    - If baseline was already broken and current is still broken (same or better), no regression.
    - If baseline passed and current fails, that's a regression.
    - If baseline had no check configured, any failure is a regression.
    """
    # Build regression
    if baseline.build_ok is not False and current.build_ok is False:
        return True
    # Test regression
    if baseline.tests_ok is not False and current.tests_ok is False:
        return True
    return False


def run_health_check(
    build_cmd: str | None = None,
    test_cmd: str | None = None,
    cwd: str | None = None,
    timeout: int = 120,
    auto_detect: bool = True,
) -> HealthCheckResult:
    """Run build and test commands, return independent health check result."""
    root = cwd or "."

    if auto_detect:
        if build_cmd is None:
            build_cmd = detect_build_command(root)
        if test_cmd is None:
            test_cmd = detect_test_command(root)

    result = HealthCheckResult(passed=True)

    # Build check
    if build_cmd:
        console.print(f"  [dim]Health check (build): {build_cmd}[/dim]")
        ok, output = _run_command(build_cmd, cwd=cwd, timeout=timeout)
        result.build_ok = ok
        result.build_output = output
        if not ok:
            result.passed = False
            result.details += f"Build FAILED: {build_cmd}\n"

    # Test check
    if test_cmd:
        console.print(f"  [dim]Health check (test): {test_cmd}[/dim]")
        ok, output = _run_command(test_cmd, cwd=cwd, timeout=timeout)
        result.tests_ok = ok
        result.test_output = output
        if not ok:
            result.passed = False
            result.details += f"Tests FAILED: {test_cmd}\n"

    if result.build_ok is None and result.tests_ok is None:
        result.details = "No build or test commands detected."
        console.print("  [dim]No health check commands detected.[/dim]")
    elif result.passed:
        console.print("  [green]Health check passed.[/green]")
    else:
        console.print(f"  [red]Health check FAILED.[/red]")

    return result
