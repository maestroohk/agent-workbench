"""Implementation of the `agent-fleet` multi-agent spawner.

Spawns N Claude agents in parallel, each in its own isolated context so
they do not pollute the user's main checkout or current shell. This is
the "multiple agents without polluting current contexts" workflow.

Backends (in order of preference):

1. `herdr` (default when installed) — uses `herdr worktree create` to make
   a fresh worktree per agent, then `herdr agent start` to launch `claude`
   in a new pane. The herdr server keeps the agents alive in the
   background; the user can attach or `herdr agent wait` for them.

2. `treehouse` (fallback when herdr is not running but treehouse is
   installed) — leases N worktrees via `treehouse get` and launches
   `claude` in detached subprocesses on each.

3. `none` (always works, no isolation) — fork-and-wait N child processes
   that each run `claude` in the same checkout. This will pollute the
   working tree if agents modify files, but it does not require herdr
   or treehouse to be installed.

`--wait` blocks until all agents report `done` (herdr) or exit (others).
`--timeout` is the per-agent wait timeout in milliseconds.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from build_prompt import assemble_prompt
from scan_repo import AGENT_DIR_NAME
from utils import (
    find_repo_root,
    first_executable,
    info,
    run_command,
)


def _herdr_available() -> bool:
    return first_executable(["herdr"]) is not None


def _treehouse_available() -> bool:
    return first_executable(["treehouse"]) is not None


def _claude_available() -> bool:
    return first_executable(["claude"]) is not None


def _herdr_server_running() -> bool:
    """Return True if the herdr daemon is up and accepting commands."""
    if not _herdr_available():
        return False
    result = run_command(["herdr", "status", "server"])
    if result.returncode != 0:
        return False
    return '"status": "running"' in result.stdout.replace(" ", "").lower() or "running" in result.stdout.lower()


def _resolve_backend(requested: str) -> str:
    """Pick the actual backend given the user's request and what's available."""
    if requested != "auto":
        return requested
    if _herdr_available() and _herdr_server_running() and _claude_available():
        return "herdr"
    if _treehouse_available() and _claude_available():
        return "treehouse"
    return "none"


def _fleet_prompt(repo: Path, task: str, agent_index: int, total: int, worktree_path: str) -> str:
    """Build a system prompt annotated with this agent's index and worktree path."""
    body, _ = assemble_prompt(repo, task=task)
    annotation = (
        "\n\n## Fleet context\n\n"
        f"- You are agent {agent_index} of {total} in a parallel agent fleet.\n"
        f"- Your worktree: `{worktree_path}`\n"
        "- You may modify files in your worktree freely; the main checkout is read-only by convention.\n"
        "- When you are finished, report a one-paragraph summary to stdout so the orchestrator can pick it up.\n"
    )
    return body.rstrip() + annotation


def _write_prompt(repo: Path, content: str, suffix: str) -> Path:
    """Write a per-agent prompt to `<repo>/.agent/SYSTEM_PROMPT.<suffix>.md`."""
    out = repo / AGENT_DIR_NAME / f"SYSTEM_PROMPT.{suffix}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return out


def _spawn_herdr(repo: Path, n: int, task: str, worktree: bool, model: Optional[str], task_text: str) -> list[dict]:
    """Spawn N herdr agents. Returns the parsed herdr worktree-create JSON for each."""
    if not _herdr_available() or not _claude_available():
        return []
    info(f"backend=herdr; spawning {n} agent(s) …")
    spawned: list[dict] = []
    for i in range(1, n + 1):
        name = f"fleet-{i}"
        wt_path = str(repo)
        if worktree:
            wt_args = ["herdr", "worktree", "create", "--label", f"agent-{name}", "--no-focus", "--json"]
            wt_result = run_command(wt_args, cwd=repo)
            if wt_result.returncode != 0:
                info(f"worktree create failed for {name}: {wt_result.stderr.strip()[:200]}; using {repo}")
            else:
                # Try to parse the JSON; fall back to the repo root if parsing fails.
                try:
                    payload = json.loads(wt_result.stdout)
                    wt_path = payload.get("path") or payload.get("worktree") or str(repo)
                except json.JSONDecodeError:
                    wt_path = wt_result.stdout.strip().splitlines()[-1] if wt_result.stdout.strip() else str(repo)
        prompt = _fleet_prompt(repo, task, i, n, wt_path)
        if task_text:
            prompt = prompt.rstrip() + f"\n\n## Task\n\n{task_text.strip()}\n"
        prompt_path = _write_prompt(repo, prompt, name)
        info(f"agent {i}/{n}: {name} worktree={wt_path} prompt={prompt_path}")
        # Read the prompt into a Python string and pass it directly via
        # --append-system-prompt. Don't shell out to `cat` — that breaks
        # on Windows where `cat` isn't on PATH inside the herdr spawn.
        prompt_body = prompt_path.read_text(encoding="utf-8")
        cmd = [
            "herdr", "agent", "start", name,
            "--cwd", wt_path,
            "--tab", "new",
            "--no-focus",
            "--",
            "claude",
            "--append-system-prompt",
            prompt_body,
        ]
        if model:
            cmd.extend(["--model", model])
        result = run_command(cmd, cwd=repo)
        if result.returncode != 0:
            info(f"herdr agent start failed for {name}: {result.stderr.strip()[:200]}")
            spawned.append({"name": name, "worktree": wt_path, "prompt": str(prompt_path), "rc": result.returncode})
        else:
            spawned.append({"name": name, "worktree": wt_path, "prompt": str(prompt_path), "rc": 0})
    return spawned


def _spawn_treehouse(repo: Path, n: int, task: str, worktree: bool, model: Optional[str], task_text: str) -> list[dict]:
    """Spawn N treehouse-leased agents in detached subprocesses."""
    if not _treehouse_available() or not _claude_available():
        return []
    info(f"backend=treehouse; spawning {n} agent(s) …")
    spawned: list[dict] = []
    for i in range(1, n + 1):
        name = f"fleet-{i}"
        wt_path = str(repo)
        if worktree:
            lease = run_command(
                ["treehouse", "get", "--lease", "--lease-holder", f"agent-{name}"],
                cwd=repo,
            )
            if lease.returncode == 0:
                wt_path = lease.stdout.strip().splitlines()[-1] if lease.stdout.strip() else str(repo)
        prompt = _fleet_prompt(repo, task, i, n, wt_path)
        if task_text:
            prompt = prompt.rstrip() + f"\n\n## Task\n\n{task_text.strip()}\n"
        prompt_path = _write_prompt(repo, prompt, name)
        info(f"agent {i}/{n}: {name} worktree={wt_path} prompt={prompt_path}")
        prompt_body = prompt_path.read_text(encoding="utf-8")
        cmd = ["claude", "--append-system-prompt", prompt_body]
        if model:
            cmd.extend(["--model", model])
        # Detached: write a launcher script and start it in the background.
        launcher = repo / AGENT_DIR_NAME / f"launch-{name}.cmd"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text(
            f"@echo off\r\n"
            f"cd /d {wt_path}\r\n"
            + " ".join(f'"{a}"' for a in cmd)
            + "\r\n",
            encoding="utf-8",
        )
        subprocess.Popen(["cmd", "/c", "start", "", str(launcher)], cwd=repo)
        spawned.append({"name": name, "worktree": wt_path, "prompt": str(prompt_path), "rc": 0, "launcher": str(launcher)})
    return spawned


def _spawn_none(repo: Path, n: int, task: str, model: Optional[str], task_text: str) -> list[dict]:
    """Spawn N claude processes in the same checkout. No isolation."""
    if not _claude_available():
        info("backend=none and claude CLI not on PATH; wrote prompts but launched no agents")
        spawned: list[dict] = []
        for i in range(1, n + 1):
            name = f"fleet-{i}"
            prompt = _fleet_prompt(repo, task, i, n, str(repo))
            if task_text:
                prompt = prompt.rstrip() + f"\n\n## Task\n\n{task_text.strip()}\n"
            prompt_path = _write_prompt(repo, prompt, name)
            spawned.append({"name": name, "worktree": str(repo), "prompt": str(prompt_path), "rc": 127, "error": "claude CLI not on PATH"})
        return spawned
    info(f"backend=none; spawning {n} agent(s) in the current checkout (no isolation) …")
    spawned = []
    for i in range(1, n + 1):
        name = f"fleet-{i}"
        prompt = _fleet_prompt(repo, task, i, n, str(repo))
        if task_text:
            prompt = prompt.rstrip() + f"\n\n## Task\n\n{task_text.strip()}\n"
        prompt_path = _write_prompt(repo, prompt, name)
        info(f"agent {i}/{n}: {name} prompt={prompt_path}")
        cmd = ["claude", "--append-system-prompt", f"@$(cat {prompt_path})"]
        if model:
            cmd.extend(["--model", model])
        proc = subprocess.Popen(cmd, cwd=str(repo))
        spawned.append({"name": name, "worktree": str(repo), "prompt": str(prompt_path), "rc": 0, "pid": proc.pid})
    return spawned


def _wait_herdr(spawned: list[dict], timeout_ms: int) -> int:
    """Block until each herdr agent reports done, or the timeout elapses. Returns 0 if all done, 1 otherwise."""
    if not spawned:
        return 1
    rc = 0
    for entry in spawned:
        if entry.get("rc"):
            rc = 1
            continue
        info(f"waiting on {entry['name']} (timeout {timeout_ms}ms) …")
        result = run_command(
            ["herdr", "agent", "wait", entry["name"], "--status", "done", "--timeout", str(timeout_ms)],
            timeout=(timeout_ms // 1000) + 30,
        )
        if result.returncode != 0:
            info(f"{entry['name']} did not finish: {result.stderr.strip()[:200]}")
            rc = 1
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Spawn N Claude agents in parallel, each in an isolated context.",
    )
    parser.add_argument("count", type=int, help="Number of agents to spawn.")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (auto-detected).")
    parser.add_argument(
        "--task",
        choices=("code", "review", "architecture", "documentation", "general"),
        default="general",
    )
    parser.add_argument("--model", default=None, help="Override the model name.")
    parser.add_argument(
        "--backend",
        choices=("auto", "herdr", "treehouse", "none"),
        default="auto",
        help="Which multi-agent backend to use. auto=prefer herdr, then treehouse, then none.",
    )
    parser.add_argument(
        "--worktree",
        choices=("auto", "yes", "no"),
        default="auto",
        help="Spawn each agent on a fresh worktree (yes) or in the current checkout (no).",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Block until all agents finish (or the timeout elapses).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600_000,
        help="Per-agent wait timeout in milliseconds (default 600000 = 10 min).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    parser.add_argument(
        "task_text",
        nargs="?",
        default="",
        help="Optional task description appended to each agent's prompt.",
    )
    args = parser.parse_args(argv)
    if args.count < 1:
        print("count must be >= 1", file=sys.stderr)
        return 2

    repo = (args.repo or find_repo_root()).resolve()
    backend = _resolve_backend(args.backend)
    info(f"repo: {repo}")
    info(f"backend: {backend}")
    use_worktree = args.worktree != "no" and backend != "none"

    if backend == "herdr":
        spawned = _spawn_herdr(repo, args.count, args.task, use_worktree, args.model, args.task_text)
    elif backend == "treehouse":
        spawned = _spawn_treehouse(repo, args.count, args.task, use_worktree, args.model, args.task_text)
    else:
        spawned = _spawn_none(repo, args.count, args.task, args.model, args.task_text)

    if args.json:
        print(json.dumps(spawned, indent=2))

    if not args.wait:
        info(f"spawned {len(spawned)} agent(s); use --wait to block, or `herdr agent wait <name>` to attach")
        return 0

    if backend == "herdr":
        return _wait_herdr(spawned, args.timeout)
    info("--wait with backend!=herdr: agents run in detached subprocesses; not blocking")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
