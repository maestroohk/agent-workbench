"""Implementation of the `agent-test` command.

Delegates to the project's existing test runner when one is detected, or
prints a clear "no tests found" message when there is nothing to run.

Order of preference:
1. `firstmate test` (if `firstmate` is on PATH or `~/firstmate/AGENTS.md` exists
   and the repo has a `firstmate.toml`). Run with `--firstmate` to force this
   even when the probe is uncertain.
2. The detected project-native runner: `dotnet test`, `mvn test`, `gradle test`,
   `pnpm test`, `yarn test`, `bun test`, `npm test`, `poetry run pytest`,
   `uv run pytest`, `pipenv run pytest`, `pytest`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from scan_repo import detect_package_managers, detect_test_frameworks
from utils import find_repo_root, first_executable, info, run_command


FIRSTMATE_HARNESS_DIR = Path(os.path.expandvars("${HOME}/firstmate"))


def _firstmate_available(repo: Path) -> bool:
    """True if firstmate is installed (binary OR ~/firstmate/AGENTS.md) AND the repo opts in."""
    if (repo / "firstmate.toml").is_file():
        if shutil.which("firstmate") or (FIRSTMATE_HARNESS_DIR / "AGENTS.md").is_file():
            return True
    return False


def _detect_command(repo: Path, *, prefer_firstmate: bool) -> list[str] | None:
    if prefer_firstmate and _firstmate_available(repo):
        return ["firstmate", "test"]
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
    parser.add_argument(
        "--firstmate",
        action="store_true",
        help="Force `firstmate test` (only meaningful if the repo has firstmate.toml).",
    )
    parser.add_argument(
        "--no-firstmate",
        action="store_true",
        help="Skip firstmate even if a firstmate.toml is present.",
    )
    args = parser.parse_args(argv)
    repo = (args.repo or find_repo_root()).resolve()

    prefer_firstmate = bool(args.firstmate) or (not args.no_firstmate and _firstmate_available(repo))
    if args.firstmate and not _firstmate_available(repo):
        info("firstmate requested but neither `firstmate` on PATH nor ~/firstmate/AGENTS.md present")
    elif prefer_firstmate and _firstmate_available(repo):
        info("firstmate.toml detected — using `firstmate test`")

    cmd = _detect_command(repo, prefer_firstmate=prefer_firstmate)
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
