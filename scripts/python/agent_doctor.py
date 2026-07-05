"""Wrapper for `firstmate doctor` (and `firstmate build`).

`firstmate` is both a CLI binary and a directory-of-skills harness
(~/firstmate/AGENTS.md). When the repo has a `firstmate.toml`, the
workbench can call `firstmate doctor` to validate the toolchain and
`firstmate build` to compile/assemble the project.

This module probes both forms (binary on PATH, harness at ~/firstmate)
and falls back gracefully when firstmate is not installed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from utils import first_executable, info, run_command


FIRSTMATE_HARNESS_DIR = Path(os.path.expandvars("${HOME}/firstmate"))


def firstmate_present(repo: Optional[Path] = None) -> bool:
    """True if firstmate is installed AND the repo opts in (has firstmate.toml)."""
    has_binary = shutil.which("firstmate") is not None
    has_harness = (FIRSTMATE_HARNESS_DIR / "AGENTS.md").is_file()
    if not (has_binary or has_harness):
        return False
    if repo is not None and not (repo / "firstmate.toml").is_file():
        return False
    return True


def _firstmate_cmd() -> Optional[list[str]]:
    """Return the command to invoke firstmate, or None if not installed."""
    bin_path = shutil.which("firstmate")
    if bin_path:
        return [bin_path]
    if (FIRSTMATE_HARNESS_DIR / "AGENTS.md").is_file():
        # The harness is launched by `claude` in its own directory; expose a
        # simple alias so callers get a stable command name.
        alias = FIRSTMATE_HARNESS_DIR / "bin" / "firstmate"
        if not alias.is_file():
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.write_text(
                "#!/usr/bin/env bash\n"
                "exec claude --cwd \"$HOME/firstmate\" \"$@\"\n",
                encoding="utf-8",
            )
            try:
                alias.chmod(0o755)
            except OSError:
                pass
        return [str(alias)]
    return None


def run_doctor(repo: Path) -> tuple[int, str]:
    """Run `firstmate doctor` in the repo. Returns (returncode, combined-output)."""
    cmd = _firstmate_cmd()
    if cmd is None:
        return 127, "firstmate not installed (run `agent-init --bootstrap=firstmate`)"
    info("firstmate doctor …")
    result = run_command([*cmd, "doctor"], cwd=repo)
    return result.returncode, result.combined()


def run_build(repo: Path) -> tuple[int, str]:
    """Run `firstmate build` in the repo. Returns (returncode, combined-output)."""
    cmd = _firstmate_cmd()
    if cmd is None:
        return 127, "firstmate not installed"
    info("firstmate build …")
    result = run_command([*cmd, "build"], cwd=repo)
    return result.returncode, result.combined()


def run_no_mistakes_check(repo: Path) -> tuple[int, str]:
    """Run `no-mistakes check --all` in the repo. Returns (returncode, combined-output)."""
    nm = first_executable(["no-mistakes"])
    if not nm:
        return 127, "no-mistakes not installed (run `agent-init --bootstrap=no-mistakes`)"
    info("no-mistakes check …")
    result = run_command([nm, "check", "--all"], cwd=repo, timeout=300)
    return result.returncode, result.combined()
