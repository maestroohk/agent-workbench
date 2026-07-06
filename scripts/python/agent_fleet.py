"""Implementation of the `agent-fleet` multi-agent spawner.

Spawns N agents in parallel, each in its own isolated context so they
do not pollute the user's main checkout or current shell. This is the
"multiple agents without polluting current contexts" workflow.

Two orthogonal axes:

  - `--backend {auto,herdr,treehouse,none}` — which *orchestrator*
    to use. `auto` picks the first one available.
  - `--runtime {claude,ollama,openai-compatible}` — which *model
    runner* to use. Defaults to `claude`; can be overridden via
    `AGENT_RUNTIME`, `~/.agent-workbench/config.toml`, or
    `--runtime`. See `scripts/python/runtime.py` for the full
    resolution order.

Backends (in order of preference):

1. `herdr` (default when installed) — uses `herdr worktree create` to make
   a fresh worktree per agent, then `herdr agent start` to launch the
   model in a new pane. The herdr server keeps the agents alive in the
   background; the user can attach or `herdr agent wait` for them.

2. `treehouse` (fallback when herdr is not running but treehouse is
   installed) — leases N worktrees via `treehouse get` and launches
   the model in detached subprocesses on each.

3. `none` (always works, no isolation) — fork-and-wait N child processes
   that each run the model in the same checkout. This will pollute the
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
    parse_json_loose,
    run_command,
)

import runtime as _runtime


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


def _resolve_backend(requested: str, runtime: _runtime.Runtime) -> str:
    """Pick the actual backend given the user's request and what's available.

    The ollama and openai-compatible runtimes map to `none` only when
    herdr / treehouse are not available: herdr's `agent start` is
    hardcoded to call the claude CLI in its own integration hook, so
    it only makes sense with the `claude` runtime.
    """
    if requested != "auto":
        return requested
    if _herdr_available() and _herdr_server_running() and _claude_available() and runtime.is_claude():
        return "herdr"
    if _treehouse_available() and _claude_available() and runtime.is_claude():
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


def _spawn_herdr(
    repo: Path,
    n: int,
    task: str,
    worktree: bool,
    runtime: _runtime.Runtime,
    task_text: str,
) -> list[dict]:
    """Spawn N herdr agents. Returns the parsed herdr worktree-create JSON for each.

    The herdr backend is reserved for the `claude` runtime — herdr's
    `agent start` is hardcoded to call the claude CLI via its
    integration hook. For other runtimes the caller routes to
    `_spawn_treehouse` or `_spawn_none`.
    """
    if not _herdr_available() or not _claude_available():
        return []
    info(f"backend=herdr; spawning {n} agent(s) with runtime={runtime.name} …")
    spawn_cmd, spawn_env = _runtime.build_spawn_args(runtime)
    runner_name = spawn_cmd[0]
    runner_path = first_executable([runner_name])
    if not runner_path:
        info(f"{runner_name} executable not found; nothing to spawn")
        return []
    spawned: list[dict] = []
    for i in range(1, n + 1):
        name = f"fleet-{i}"
        wt_path = str(repo)
        if worktree:
            # Pass `--cwd <repo>` so herdr has an active workspace when no
            # herdr workspace is currently set, and `--json` so we can
            # parse the worktree path out of the envelope.
            wt_args = [
                "herdr", "worktree", "create",
                "--cwd", str(repo),
                "--label", f"agent-{name}",
                "--no-focus", "--json",
            ]
            wt_result = run_command(wt_args, cwd=repo)
            if wt_result.returncode != 0:
                info(f"worktree create failed for {name}: {wt_result.stderr.strip()[:200]}; using {repo}")
            else:
                # Parse herdr's JSON envelope. Tolerant of two shapes:
                #   1. {"worktree_created":{"worktree":{"path":"..."}}}
                #   2. {"path":"..."}
                payload = parse_json_loose(wt_result.stdout)
                if payload:
                    inner = payload.get("worktree_created") if isinstance(payload.get("worktree_created"), dict) else payload
                    wt_obj = inner.get("worktree") if isinstance(inner, dict) else None
                    if isinstance(wt_obj, dict) and wt_obj.get("path"):
                        wt_path = str(wt_obj["path"])
                    elif isinstance(inner, dict) and inner.get("path"):
                        wt_path = str(inner["path"])
                    else:
                        info(f"worktree JSON for {name} did not contain a path; using {repo}")
                else:
                    info(f"worktree JSON for {name} did not parse; using {repo}")
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
            "--split", "right",
            "--no-focus",
            "--",
            runner_path,
            "--append-system-prompt",
            prompt_body,
            "--model",
            runtime.model,
        ]
        # The openai-compatible runtime needs ANTHROPIC_BASE_URL and
        # ANTHROPIC_AUTH_TOKEN in the child's env. The herdr server
        # inherits its parent's env, so we merge the overrides for
        # the duration of this call.
        saved_env: dict[str, Optional[str]] = {}
        if spawn_env:
            for key, value in spawn_env.items():
                saved_env[key] = os.environ.get(key)
                os.environ[key] = value
        try:
            result = run_command(cmd, cwd=repo)
        finally:
            for key, old_value in saved_env.items():
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value
        if result.returncode != 0:
            info(f"herdr agent start failed for {name}: {result.stderr.strip()[:200]}")
            spawned.append({"name": name, "worktree": wt_path, "prompt": str(prompt_path), "rc": result.returncode})
        else:
            spawned.append({"name": name, "worktree": wt_path, "prompt": str(prompt_path), "rc": 0})
    return spawned


def _spawn_treehouse(
    repo: Path,
    n: int,
    task: str,
    worktree: bool,
    runtime: _runtime.Runtime,
    task_text: str,
) -> list[dict]:
    """Spawn N treehouse-leased agents in detached subprocesses.

    Same caveat as `_spawn_herdr`: treehouse worktrees pair with
    the claude CLI by default. For non-claude runtimes we still
    launch the resolved runner, but the user is on their own for
    wiring treehouse's external-spawn contract.
    """
    if not _treehouse_available():
        return []
    info(f"backend=treehouse; spawning {n} agent(s) with runtime={runtime.name} …")
    spawn_cmd, spawn_env = _runtime.build_spawn_args(runtime)
    runner_name = spawn_cmd[0]
    runner_path = first_executable([runner_name])
    if not runner_path:
        info(f"{runner_name} executable not found; nothing to spawn")
        return []
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
        cmd = [runner_path, "--append-system-prompt", prompt_body, "--model", runtime.model]
        # Detached: write a launcher script and start it in the background.
        launcher = repo / AGENT_DIR_NAME / f"launch-{name}.cmd"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher_env_lines = ""
        if spawn_env:
            for key, value in spawn_env.items():
                launcher_env_lines += f"set {key}={value}\r\n"
        launcher.write_text(
            f"@echo off\r\n"
            f"cd /d {wt_path}\r\n"
            + launcher_env_lines
            + " ".join(f'"{a}"' for a in cmd)
            + "\r\n",
            encoding="utf-8",
        )
        subprocess.Popen(["cmd", "/c", "start", "", str(launcher)], cwd=repo)
        spawned.append({"name": name, "worktree": wt_path, "prompt": str(prompt_path), "rc": 0, "launcher": str(launcher)})
    return spawned


def _spawn_none(
    repo: Path,
    n: int,
    task: str,
    runtime: _runtime.Runtime,
    task_text: str,
) -> list[dict]:
    """Spawn N agents in the same checkout. No isolation.

    This is the only path that works for all three runtimes
    (claude, ollama, openai-compatible) without depending on
    herdr or treehouse. The `openai-compatible` runtime needs
    the env overrides applied to the spawned Popen so the
    child process sees them.
    """
    spawn_cmd, spawn_env = _runtime.build_spawn_args(runtime)
    runner_name = spawn_cmd[0]
    runner_path = first_executable([runner_name])
    if not runner_path:
        info(f"backend=none and {runner_name} CLI not on PATH; wrote prompts but launched no agents")
        spawned: list[dict] = []
        for i in range(1, n + 1):
            name = f"fleet-{i}"
            prompt = _fleet_prompt(repo, task, i, n, str(repo))
            if task_text:
                prompt = prompt.rstrip() + f"\n\n## Task\n\n{task_text.strip()}\n"
            prompt_path = _write_prompt(repo, prompt, name)
            spawned.append({"name": name, "worktree": str(repo), "prompt": str(prompt_path), "rc": 127, "error": f"{runner_name} CLI not on PATH"})
        return spawned
    info(f"backend=none; spawning {n} agent(s) in the current checkout (no isolation) with runtime={runtime.name} …")
    spawned = []
    child_env = None
    if spawn_env:
        child_env = os.environ.copy()
        child_env.update(spawn_env)
    for i in range(1, n + 1):
        name = f"fleet-{i}"
        prompt = _fleet_prompt(repo, task, i, n, str(repo))
        if task_text:
            prompt = prompt.rstrip() + f"\n\n## Task\n\n{task_text.strip()}\n"
        prompt_path = _write_prompt(repo, prompt, name)
        info(f"agent {i}/{n}: {name} prompt={prompt_path}")
        # We shell out with the resolved runner. For the openai-compatible
        # runtime the runner is the `claude` CLI; for ollama it's `ollama`;
        # for the claude runtime it's `claude`. The model flag is appended
        # so each agent knows which model to use.
        cmd = [runner_path, "--model", runtime.model]
        if runtime.is_claude() or runtime.is_openai_compatible():
            cmd.extend(["--append-system-prompt", prompt_path.read_text(encoding="utf-8")])
        else:  # ollama: pass the prompt via stdin-equivalent
            cmd.append(prompt_path.read_text(encoding="utf-8"))
        proc = subprocess.Popen(cmd, cwd=str(repo), env=child_env)
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


def _build_argparser() -> argparse.ArgumentParser:
    """Build the argparse parser for `agent-fleet`.

    Extracted from `main()` so tests can drive the parser directly."""
    parser = argparse.ArgumentParser(
        description="Spawn N agents in parallel, each in an isolated context.",
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
        "--runtime",
        choices=_runtime.RUNTIMES,
        default=None,
        help="Which model runner to use. claude=Anthropic Claude Code, "
             "ollama=local Ollama, openai-compatible=Claude Code pointed at "
             "ANTHROPIC_BASE_URL. Default: from AGENT_RUNTIME or config. "
             "The herdr and treehouse backends require --runtime=claude.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="(openai-compatible) The Anthropic-protocol base URL "
             "(e.g. http://localhost:1234/v1 for LM Studio).",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="(openai-compatible) Name of the env var holding the API key.",
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    if args.count < 1:
        print("count must be >= 1", file=sys.stderr)
        return 2

    repo = (args.repo or find_repo_root()).resolve()
    info(f"repo: {repo}")

    # Resolve the runtime (CLI > AGENT_RUNTIME > config > default).
    config = _runtime.load_config()
    rt_name, _ = _runtime.resolve_runtime(
        cli_value=args.runtime,
        env_value=os.environ.get("AGENT_RUNTIME"),
        config=config,
    )
    rt_model, _ = _runtime.resolve_model(
        rt_name,
        cli_model=args.model,
        env_model=os.environ.get("AGENT_MODEL"),
        config=config,
    )
    runtime = _runtime.Runtime(
        name=rt_name,
        model=rt_model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        source="cli-or-config",
    )
    for line in _runtime.runtime_summary_lines(runtime):
        info(line)

    backend = _resolve_backend(args.backend, runtime)
    info(f"backend: {backend}")
    use_worktree = args.worktree != "no" and backend != "none"

    if backend == "herdr":
        spawned = _spawn_herdr(repo, args.count, args.task, use_worktree, runtime, args.task_text)
    elif backend == "treehouse":
        spawned = _spawn_treehouse(repo, args.count, args.task, use_worktree, runtime, args.task_text)
    else:
        spawned = _spawn_none(repo, args.count, args.task, runtime, args.task_text)

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
