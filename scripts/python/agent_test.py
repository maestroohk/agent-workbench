"""Implementation of the `agent-test` command.

Delegates to the project's existing test runner when one is detected, or
prints a clear "no tests found" message when there is nothing to run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scan_repo import detect_package_managers, detect_test_frameworks
from utils import find_repo_root, info, run_command


def _detect_command(repo: Path) -> list[str] | None:
    managers = detect_package_managers(repo)
    frameworks = detect_test_frameworks(repo)
    if "dotnet" in managers:
        return ["dotnet", "test", "-c", "Release"]
    if "maven" in managers:
        return ["mvn", "-B", "test"]
    if "gradle" in managers:
        return ["./gradlew", "test"] if (repo / "gradlew").is_file() else ["gradle", "test"]
    pm = None
    for candidate in ("pnpm", "yarn", "bun", "npm"):
        if candidate in managers:
            pm = candidate
            break
    if pm:
        return [pm, "test"]
    if "poetry" in managers:
        return ["poetry", "run", "pytest"]
    if "uv" in managers:
        return ["uv", "run", "pytest"]
    if "pipenv" in managers:
        return ["pipenv", "run", "pytest"]
    if any(p.is_file() for p in (repo / "pyproject.toml", repo / "pytest.ini", repo / "tests")):
        return ["pytest"]
    if not frameworks:
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the project's test suite if one is detected.")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (auto-detected).")
    parser.add_argument("--dry-run", action="store_true", help="Print the command without running it.")
    args = parser.parse_args(argv)
    repo = (args.repo or find_repo_root()).resolve()
    cmd = _detect_command(repo)
    if cmd is None:
        print("no test runner detected", file=sys.stderr)
        return 2
    info(f"running: {' '.join(cmd)}")
    if args.dry_run:
        print(" ".join(cmd))
        return 0
    result = run_command(cmd, cwd=repo)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
