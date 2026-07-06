"""Wrapper for `firstmate doctor` (and `firstmate build`).

`firstmate` is a directory-of-skills harness at `~/firstmate/AGENTS.md`
plus a `bin/fm-*.sh` toolbelt. It does NOT ship a `firstmate doctor`
or `firstmate test` subcommand — those names appear in the workbench
docs and the original `agent_doctor` shim creation assumed them, but
upstream has never had them.

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
    """True if firstmate is installed (shim on PATH or harness at ~/firstmate).

    The previous version required a `firstmate.toml` in the repo, on the
    theory that firstmate is opt-in per project. Upstream firstmate has
    no such config format; the requirement made the workbench *never*
    report on firstmate. A `repo` argument is still accepted for
    backward compatibility, but no longer gates the result.
    """
    has_binary = shutil.which("firstmate") is not None
    has_harness = (FIRSTMATE_HARNESS_DIR / "AGENTS.md").is_file()
    return has_binary or has_harness


def firstmate_version() -> Optional[str]:
    """Best-effort version string for an installed firstmate harness.

    Returns the most recent commit SHA in the clone, or None if the
    harness is not installed. Upstream has no release tags, so a
    commit hash is the most honest answer.
    """
    if not (FIRSTMATE_HARNESS_DIR / ".git").is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(FIRSTMATE_HARNESS_DIR), "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()[:80]


def _firstmate_cmd() -> Optional[list[str]]:
    """Return the command to invoke firstmate, or None if not installed.

    Order of preference:
    1. A `firstmate` binary on PATH (set up by the bootstrap shim).
    2. The harness at ~/firstmate/bin/firstmate if it exists.
    3. None.
    """
    bin_path = shutil.which("firstmate")
    if bin_path:
        return [bin_path]
    harness_entry = FIRSTMATE_HARNESS_DIR / "bin" / "firstmate"
    if harness_entry.is_file():
        return [str(harness_entry)]
    return None


def run_doctor(repo: Path) -> tuple[int, str]:
    """Surface the firstmate harness's own preflight state.

    Upstream firstmate has no `firstmate doctor` subcommand. The
    workbench historically called it anyway and silently swallowed
    the failure. We now do a real preflight check: enumerate the
    `bin/fm-*.sh` toolbelt and the `AGENTS.md` ops manual so the
    `agent-check` report is honest about what is and isn't there.
    """
    if not firstmate_present(repo):
        return 127, "firstmate not installed (run `agent-init --bootstrap=firstmate`)"
    info("firstmate preflight …")
    harness_bin = FIRSTMATE_HARNESS_DIR / "bin"
    scripts = sorted(p.name for p in harness_bin.glob("fm-*.sh")) if harness_bin.is_dir() else []
    agents_md = (FIRSTMATE_HARNESS_DIR / "AGENTS.md").is_file()
    if not scripts and not agents_md:
        return 1, f"firstmate harness at {FIRSTMATE_HARNESS_DIR} is incomplete (no bin/fm-*.sh, no AGENTS.md)"
    return 0, f"harness at {FIRSTMATE_HARNESS_DIR}: {len(scripts)} fm-*.sh scripts, AGENTS.md={'present' if agents_md else 'missing'}"


def run_build(repo: Path) -> tuple[int, str]:
    """`firstmate build` is not a real upstream subcommand. Report that.

    The workbench's `agent-check` previously tried to call this and
    silently swallowed the failure. We surface a clear skip-message
    so the report is honest.
    """
    return 0, "firstmate: no `build` subcommand upstream (workbench skips)"


def run_no_mistakes_doctor(repo: Path) -> tuple[int, str]:
    """Run `no-mistakes doctor` in the repo. Returns (returncode, combined-output).

    `no-mistakes` doesn't have a `check` subcommand — its surface is
    `init` (setup the gate), `doctor` (system health), `status` (current
    run), and `axiom` (agent-facing TOON). For an `agent-check` we run
    `doctor` because it always works regardless of whether the repo has
    been initialized as a gate.
    """
    nm = first_executable(["no-mistakes"])
    if not nm:
        return 127, "no-mistakes not installed (run `agent-init --bootstrap=no-mistakes`)"
    info("no-mistakes doctor …")
    result = run_command([nm, "doctor"], cwd=repo, timeout=60)
    return result.returncode, result.combined()


def run_no_mistakes_status(repo: Path) -> tuple[int, str]:
    """Run `no-mistakes status` in the repo. Returns (returncode, combined-output).

    Only meaningful after `no-mistakes init` has been run in the repo
    (which sets up the gate). Returns rc=127 with a clear message
    otherwise so the caller can skip silently.
    """
    nm = first_executable(["no-mistakes"])
    if not nm:
        return 127, "no-mistakes not installed"
    result = run_command([nm, "status"], cwd=repo, timeout=30)
    # rc != 0 with "not initialized" message means the gate isn't set up.
    if result.returncode != 0 and "not initialized" in (result.stderr or "").lower():
        return 127, "no-mistakes gate not initialized in this repo (run `no-mistakes init`)"
    return result.returncode, result.combined()
