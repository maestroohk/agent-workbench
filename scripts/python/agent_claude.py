"""Implementation of the `agent-claude` launcher.

Builds the system prompt and prepares it for the model runner. Behaviour:

- `--show-prompt` prints the assembled prompt and exits.
- `--write-only` writes the prompt to `<repo>/.agent/SYSTEM_PROMPT.md` and exits.
- Default: writes the prompt, then launches the model runner.

Two orthogonal axes:

  - `--backend {auto,herdr,claude,ollama,none}` — which *orchestrator*
    to use (herdr pane isolation, direct claude, etc.). auto = prefer
    herdr, then direct claude, then ollama fallback.
  - `--runtime {claude,ollama,openai-compatible}` — which *model
    runner* to use. Defaults to `claude`; can be overridden via
    `AGENT_RUNTIME`, `~/.agent-workbench/config.toml`, or
    `--runtime`. See `scripts/python/runtime.py` for the full
    resolution order.

Runner selection (in order of preference, applied on top of the
backend choice):

1. The `claude` CLI (Anthropic Claude Code). Reads the system prompt from
   `<repo>/.agent/SYSTEM_PROMPT.md` (Claude Code's default location).
2. `herdr agent start <name> -- <argv…>` — launches `claude` in an isolated
   herdr pane on a fresh worktree. Used when `--backend=herdr`.
3. `ollama run <model>` — local model fallback when `claude` is not installed.
4. Print a paste-ready summary if no runner is found.

The default model is runtime-specific: `opus` for the `claude` runtime,
`minimax-m3:cloud` for `ollama` and `openai-compatible`. Override with
`--model`, `AGENT_MODEL`, or the `~/.agent-workbench/config.toml` file.

If herdr is present, `agent-claude` is also the place we wire the
`herdr integration install claude` step (one-time setup that registers
herdr's agent-state hook with Claude Code).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from build_prompt import assemble_prompt
from scan_repo import AGENT_DIR_NAME
from utils import (
    DEFAULT_MODEL,
    find_repo_root,
    first_executable,
    info,
    parse_json_loose,
    resolve_executable,
    run_command,
    workbench_root,
)

import runtime as _runtime


CONFIG_FILENAME = "config.toml"


def resolve_model(cli_value: Optional[str]) -> str:
    """Resolve the model name from CLI > env > config > default.

    This is the legacy single-string resolver kept for backwards
    compatibility with `agent_claude` callers that only have a CLI
    value. New code should use `_runtime.resolve_model()` for the
    full per-runtime resolution order.
    """
    if cli_value:
        return cli_value
    env = os.environ.get("AGENT_MODEL")
    if env:
        return env
    config_path = Path.home() / ".agent-workbench" / CONFIG_FILENAME
    if config_path.is_file():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "model":
                return value.strip().strip('"').strip("'")
    return DEFAULT_MODEL


def _resolve_full_runtime(
    cli_runtime: Optional[str],
    cli_model: Optional[str],
    cli_base_url: Optional[str],
    cli_api_key_env: Optional[str],
) -> _runtime.Runtime:
    """Resolve the runtime + model + endpoint configuration.

    Used by `main()` to combine the runtime-resolution order
    (CLI > AGENT_RUNTIME > config > default) with the model-resolution
    order. The base-url and api-key-env are passed through verbatim
    to the openai-compatible spawn path.
    """
    config = _runtime.load_config()
    rt_name, _ = _runtime.resolve_runtime(
        cli_value=cli_runtime,
        env_value=os.environ.get("AGENT_RUNTIME"),
        config=config,
    )
    rt_model, _ = _runtime.resolve_model(
        rt_name,
        cli_model=cli_model,
        env_model=os.environ.get("AGENT_MODEL"),
        config=config,
    )
    return _runtime.Runtime(
        name=rt_name,
        model=rt_model,
        base_url=cli_base_url,
        api_key_env=cli_api_key_env,
        source="cli-or-config",
    )


def write_prompt_to_repo(repo: Path, prompt: str) -> Path:
    """Write the prompt to `<repo>/.agent/SYSTEM_PROMPT.md` and return the path."""
    out = repo / AGENT_DIR_NAME / "SYSTEM_PROMPT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    return out


def _herdr_available() -> bool:
    return resolve_executable("herdr") is not None


def _ensure_herdr_claude_integration() -> bool:
    """Run `herdr integration install claude` if herdr is present and the hook isn't yet installed.

    This is a one-time, idempotent setup step: herdr prints "installed claude integration hook"
    the first time and is a no-op afterwards.
    """
    if not _herdr_available():
        return False
    hook_path = Path.home() / ".claude" / "hooks" / "herdr-agent-state.ps1"
    if hook_path.is_file():
        return True
    info("installing herdr claude integration hook …")
    result = run_command(["herdr", "integration", "install", "claude"])
    if result.returncode != 0:
        info(f"herdr integration install claude failed: {result.stderr.strip()[:200]}")
        return False
    return True


def _spawn_herdr_agent(
    repo: Path,
    prompt_path: Path,
    runtime: _runtime.Runtime,
    agent_name: str = "primary",
) -> int:
    """Launch the model runner in a new herdr agent on a fresh worktree.

    Returns the herdr invocation's returncode. The herdr server keeps the
    process alive after we return; the user can attach with
    `herdr agent attach <name>` or `herdr agent wait <name> --status done`.
    """
    if not _ensure_herdr_claude_integration():
        info("herdr unavailable or integration hook failed; falling back")
        return _spawn_claude(repo, runtime)
    info(f"spawning herdr agent: {agent_name}")
    herdr = resolve_executable("herdr")
    if not herdr:
        info("herdr executable not found; falling back")
        return _spawn_claude(repo, runtime)
    worktree_args = [
        herdr,
        "worktree",
        "create",
        "--cwd",
        str(repo),
        "--label",
        f"agent-{agent_name}",
        "--no-focus",
        "--json",
    ]
    wt_result = run_command(worktree_args, cwd=repo)
    if wt_result.returncode != 0:
        info(
            f"herdr worktree create failed ({wt_result.stderr.strip()[:120] or 'no stderr'}); "
            f"running agent in repo root instead"
        )
        worktree_path = str(repo)
    else:
        # Parse herdr's JSON envelope to extract the actual worktree path.
        # The previous code took stdout.strip() as the path, which sent
        # the whole JSON blob as `--cwd` and made the agent land in $HOME.
        payload = parse_json_loose(wt_result.stdout)
        inner = payload.get("worktree_created") if isinstance(payload, dict) and isinstance(payload.get("worktree_created"), dict) else (payload or {})
        wt_obj = inner.get("worktree") if isinstance(inner, dict) else None
        if isinstance(wt_obj, dict) and wt_obj.get("path"):
            worktree_path = str(wt_obj["path"])
        elif isinstance(inner, dict) and inner.get("path"):
            worktree_path = str(inner["path"])
        else:
            worktree_path = str(repo)
            info(
                f"herdr worktree create did not return a path; "
                f"running agent in repo root instead"
            )
    info(f"worktree: {worktree_path}")
    # Resolve the inner runner to a real Windows executable (e.g.
    # `claude.cmd` / `ollama.exe`) before handing it to herdr, so
    # herdr's own CreateProcessW call does not hit WinError 193 on
    # the bare npm shim.
    spawn_cmd, spawn_env = _runtime.build_spawn_args(runtime)
    runner_name = spawn_cmd[0]
    runner_path = resolve_executable(runner_name)
    if not runner_path:
        info(f"{runner_name} executable not found; falling back")
        if runtime.is_claude():
            return _spawn_ollama(repo, runtime.model)
        return 127
    # Pass the prompt as `--append-system-prompt-file <path>` so we don't
    # have to shell out to `cat` (which is not on PATH inside the herdr
    # spawn on Windows) and we don't have to inline a multi-KB string into
    # a command line. Claude Code reads the file directly.
    prompt_body = prompt_path.read_text(encoding="utf-8")
    cmd = [
        herdr,
        "agent",
        "start",
        agent_name,
        "--cwd",
        worktree_path,
        "--split",
        "right",
        "--no-focus",
        "--",
        runner_path,
        "--append-system-prompt",
        prompt_body,
        "--model",
        runtime.model,
    ]
    info(f"running: herdr agent start {agent_name} -- {runner_path} --append-system-prompt <{prompt_path}> --model {runtime.model}")
    # The openai-compatible runtime needs ANTHROPIC_BASE_URL and
    # ANTHROPIC_AUTH_TOKEN in the child's env. The herdr server
    # inherits its parent's env, so we just merge the overrides
    # into the current os.environ for the duration of this call.
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
        info(
            f"herdr agent start failed (exit {result.returncode}); "
            f"falling back to direct claude"
        )
        return _spawn_claude(repo, runtime)
    info(f"herdr agent '{agent_name}' started in {worktree_path}")
    return result.returncode


def _spawn_claude(repo: Path, runtime: _runtime.Runtime) -> int:
    """Launch the runner in the current repo (no herdr isolation).

    For the `claude` runtime, fall back to `ollama run <model>` when
    the claude CLI is missing. For `ollama` runtime, just hand off to
    `_spawn_ollama` (so the runner name resolves consistently). For
    `openai-compatible`, we re-use the claude CLI with the env
    overrides applied; if the binary is missing we cannot fall back
    to ollama, so we return 127.
    """
    spawn_cmd, spawn_env = _runtime.build_spawn_args(runtime)
    runner_name = spawn_cmd[0]
    runner = resolve_executable(runner_name)
    if not runner:
        info(f"{runner_name} CLI not found on PATH; falling back to ollama run")
        if runtime.is_claude() or runtime.is_openai_compatible():
            return _spawn_ollama(repo, runtime.model)
        return 127
    info(f"running: {runner} (cwd={repo}, runtime={runtime.name}, model={runtime.model})")
    argv = [runner, *spawn_cmd[1:]]
    if runtime.is_claude() or runtime.is_openai_compatible():
        # Claude Code accepts the prompt via --append-system-prompt.
        # The prompt is also written to .agent/SYSTEM_PROMPT.md so
        # Claude Code auto-loads it on its own.
        prompt_path = repo / AGENT_DIR_NAME / "SYSTEM_PROMPT.md"
        argv.extend(["--append-system-prompt", prompt_path.read_text(encoding="utf-8")])
    child_env = None
    if spawn_env:
        child_env = os.environ.copy()
        child_env.update(spawn_env)
    result = run_command(argv, cwd=repo, env=child_env)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def _spawn_ollama(repo: Path, model: str) -> int:
    """Fall back to ollama run <model> when no other runner is available."""
    ollama = resolve_executable("ollama")
    if not ollama:
        print("no model runner found", file=sys.stderr)
        print("install the claude CLI (npm i -g @anthropic-ai/claude-code) or ollama (winget install Ollama.Ollama)", file=sys.stderr)
        return 127
    info(f"running: {ollama} run {model} (cwd={repo})")
    result = run_command([ollama, "run", model], cwd=repo)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def _build_argparser() -> argparse.ArgumentParser:
    """Build the argparse parser for `agent-claude`.

    Extracted from `main()` so tests can drive the parser directly."""
    parser = argparse.ArgumentParser(description="Launch the model with the assembled system prompt.")
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
             "ANTHROPIC_BASE_URL. Default: from AGENT_RUNTIME or config.",
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
        help="(openai-compatible) Name of the env var holding the API key "
             "(e.g. OPENAI_API_KEY). The value is read at spawn time.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the assembled system prompt to stdout instead of launching the model.",
    )
    parser.add_argument(
        "--print-loaded",
        action="store_true",
        help="Print the list of files that contributed to the prompt.",
    )
    parser.add_argument(
        "--write-only",
        action="store_true",
        help="Write the system prompt to .agent/SYSTEM_PROMPT.md and exit.",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "herdr", "claude", "ollama", "none"),
        default="auto",
        help="Which orchestrator to use. auto=prefer herdr if available, else "
             "claude, else ollama. none=print the prompt and stop. "
             "This is orthogonal to --runtime, which selects the model runner.",
    )
    parser.add_argument(
        "--worktree",
        choices=("auto", "yes", "no"),
        default="auto",
        help="With --backend=herdr: spawn the agent on a fresh worktree (yes) or in the current checkout (no).",
    )
    parser.add_argument(
        "task_text",
        nargs="?",
        default="",
        help="Optional task description appended to the prompt.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    repo = (args.repo or find_repo_root()).resolve()
    body, loaded = assemble_prompt(repo, task=args.task)
    if args.task_text:
        body = body.rstrip() + "\n\n## Task\n\n" + args.task_text.strip() + "\n"
    if args.print_loaded:
        for path in loaded:
            info(f"loaded {path}")
    if args.show_prompt:
        sys.stdout.write(body)
        return 0
    prompt_path = write_prompt_to_repo(repo, body)
    info(f"wrote {prompt_path}")
    if args.write_only:
        return 0
    if args.backend == "none":
        info("backend=none; prompt written but not run")
        return 0

    # Resolve the runtime (CLI > AGENT_RUNTIME > config > default) and
    # print the same "what we are going to use" block that `agent-go`
    # prints. The backend picks the orchestrator; the runtime picks the
    # model runner; both axes are evaluated independently.
    runtime = _resolve_full_runtime(
        cli_runtime=args.runtime,
        cli_model=args.model,
        cli_base_url=args.base_url,
        cli_api_key_env=args.api_key_env,
    )
    for line in _runtime.runtime_summary_lines(runtime):
        info(line)

    backend = args.backend
    if backend == "auto":
        backend = "herdr" if _herdr_available() and resolve_executable("claude") else ("claude" if resolve_executable("claude") else "ollama")
        info(f"auto-selected backend: {backend}")

    # The ollama and openai-compatible backends map to a single
    # orchestrator path (the user picked the model runner; we just
    # launch it in the current shell). The herdr path is reserved
    # for the `claude` runtime because herdr's `claude` integration
    # hook is what gets installed by `_ensure_herdr_claude_integration`.
    if backend == "herdr" and not runtime.is_claude():
        info(
            f"--backend=herdr requires the claude runtime; "
            f"runtime={runtime.name} -> using direct {runtime.name} spawn"
        )
        return _spawn_claude(repo, runtime)
    if backend == "herdr":
        use_worktree = args.worktree == "yes" or (args.worktree == "auto" and _herdr_available())
        if use_worktree:
            return _spawn_herdr_agent(repo, prompt_path, runtime)
        return _spawn_claude(repo, runtime)
    if backend == "claude":
        return _spawn_claude(repo, runtime)
    if backend == "ollama":
        # `agent-claude --backend=ollama` is a thin wrapper around
        # the ollama spawn; we keep it for backwards compatibility
        # but the user-facing path for ollama is `--runtime ollama`.
        return _spawn_ollama(repo, runtime.model)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
