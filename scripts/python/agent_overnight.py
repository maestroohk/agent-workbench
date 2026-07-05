"""`agent-overnight` — wrap gnhf with safe defaults for long autonomous runs.

What `gnhf` is:
  A loop driver that runs a coding agent (Claude Code, Codex, Copilot,
  OpenCode, Pi, etc.) inside a git repo. Each successful iteration is
  a separate commit. Aborts on `--max-iterations`, `--max-tokens`, or
  the agent reporting `--stop-when`. Failed iterations get reset.

`agent-overnight` adds three things on top of `gnhf`:
  1. Sensible defaults: `--worktree` (isolated from the main checkout),
     `--max-iterations 50`, `--max-tokens 100000`, `--agent claude`
     unless overridden.
  2. A `--task-file` so the prompt can live in version control
     (`overnight-task.md`).
  3. A preflight check: refuses to run if the repo is dirty (would
     muddy the commit log) or if gnhf isn't installed.

The point: `agent-overnight "fix the warnings in src/"` is a one-liner
the user can run before bed. By morning, the gnhf/<slug> branch has up
to 50 commits, each addressing one warning.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from utils import find_repo_root, info


DEFAULT_MAX_ITERATIONS = 50
DEFAULT_MAX_TOKENS = 100_000
DEFAULT_AGENT = "claude"


def _gnhf_available() -> bool:
    return shutil.which("gnhf") is not None or shutil.which("gnhf.cmd") is not None


def _resolve_task_text(args: argparse.Namespace) -> str:
    """Return the prompt text, from --task-file, positional, or both."""
    parts: list[str] = []
    if args.task_file:
        path = Path(args.task_file)
        if not path.is_file():
            sys.exit(f"agent-overnight: --task-file not found: {path}")
        parts.append(path.read_text(encoding="utf-8").strip())
    if args.task_text:
        parts.append(args.task_text.strip())
    if not parts:
        sys.exit("agent-overnight: provide a task as a positional argument or --task-file <path>")
    return "\n\n".join(parts)


def _is_git_dirty(repo: Path) -> bool:
    """True if `git status --porcelain` returns any output."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=15,
    )
    return bool(result.stdout.strip())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a gnhf overnight loop with safe defaults (worktree, iteration cap, token cap).",
    )
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (auto-detected).")
    parser.add_argument(
        "--task-file",
        type=Path,
        default=None,
        help="Path to a file holding the task description (e.g. overnight-task.md).",
    )
    parser.add_argument(
        "--agent",
        default=DEFAULT_AGENT,
        help=f"Which agent gnhf should drive (default: {DEFAULT_AGENT}).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help=f"Abort after N iterations (default: {DEFAULT_MAX_ITERATIONS}).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Abort after N tokens (default: {DEFAULT_MAX_TOKENS}).",
    )
    parser.add_argument(
        "--stop-when",
        default=None,
        help="Optional gnhf --stop-when marker (e.g. 'all warnings fixed').",
    )
    parser.add_argument(
        "--no-worktree",
        action="store_true",
        help="Run in the current checkout instead of an isolated worktree (NOT recommended).",
    )
    parser.add_argument(
        "--current-branch",
        action="store_true",
        help="Use the current branch instead of creating a gnhf/<slug> branch.",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push the gnhf branch after each successful iteration.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Skip the preflight check that refuses to run on a dirty repo.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the gnhf command that would be run, and exit.",
    )
    parser.add_argument(
        "task_text",
        nargs="?",
        default="",
        help="The task description (or use --task-file).",
    )
    args = parser.parse_args(argv)

    if not _gnhf_available():
        info("gnhf is not installed. Run: agent-init --bootstrap=gnhf")
        return 127

    repo = (args.repo or find_repo_root()).resolve()
    info(f"repo: {repo}")

    if not args.allow_dirty and _is_git_dirty(repo):
        info(f"repo {repo} is dirty. Commit or stash your changes first,")
        info("or pass --allow-dirty to override (not recommended — gnhf will")
        info("mix your WIP into the commit log).")
        return 2

    task = _resolve_task_text(args)
    info(f"task: {task.splitlines()[0] if task else '(empty)'}…")

    cmd: list[str] = [
        "gnhf",
        task,
        "--agent", args.agent,
        "--max-iterations", str(args.max_iterations),
        "--max-tokens", str(args.max_tokens),
    ]
    if not args.no_worktree:
        cmd.append("--worktree")
    if args.current_branch:
        cmd.append("--current-branch")
    if args.push:
        cmd.append("--push")
    if args.stop_when:
        cmd.extend(["--stop-when", args.stop_when])

    if args.dry_run:
        print(" ".join(f'"{a}"' if " " in a else a for a in cmd))
        return 0

    info(f"running: {' '.join(cmd[:6])}… (full command logged above)")
    result = subprocess.run(cmd, cwd=str(repo))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
