"""Implementation of the `agent-claude` launcher.

Builds the system prompt and prepares it for the model runner. Behaviour:

- `--show-prompt` prints the assembled prompt and exits.
- `--write-only` writes the prompt to `<repo>/.agent/SYSTEM_PROMPT.md` and exits.
- Default: writes the prompt, then launches the model runner.

Runner selection (in order of preference):
1. The `claude` CLI (Anthropic Claude Code). Reads the system prompt from
   `<repo>/.agent/SYSTEM_PROMPT.md` (Claude Code's default location).
2. `herdr agent start <name> -- <argv…>` — launches `claude` in an isolated
   herdr pane on a fresh worktree. Used when `--backend=herdr`.
3. `ollama run <model>` — local model fallback when `claude` is not installed.
4. Print a paste-ready summary if no runner is found.

The default model is `minimax-m3:cloud`; override with `--model`,
`AGENT_MODEL`, or the `~/.agent-workbench/config.toml` file.

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
    resolve_executable,
    run_command,
    workbench_root,
)


CONFIG_FILENAME = "config.toml"


def resolve_model(cli_value: Optional[str]) -> str:
    """Resolve the model name from CLI > env > config > default."""
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


def _spawn_herdr_agent(repo: Path, prompt_path: Path, model: str, agent_name: str = "primary") -> int:
    """Launch `claude` in a new herdr agent on a fresh worktree.

    Returns the herdr invocation's returncode. The herdr server keeps the
    process alive after we return; the user can attach with
    `herdr agent attach <name>` or `herdr agent wait <name> --status done`.
    """
    if not _ensure_herdr_claude_integration():
        info("herdr unavailable or integration hook failed; falling back")
        return _spawn_claude(repo, model)
    info(f"spawning herdr agent: {agent_name}")
    herdr = resolve_executable("herdr")
    if not herdr:
        info("herdr executable not found; falling back")
        return _spawn_claude(repo, model)
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
        worktree_path = wt_result.stdout.strip() or str(repo)
    info(f"worktree: {worktree_path}")
    # Resolve the inner `claude` to a real Windows executable (e.g.
    # `claude.cmd`) before handing it to herdr, so herdr's own
    # CreateProcessW call does not hit WinError 193 on the bare npm shim.
    claude = resolve_executable("claude")
    if not claude:
        info("claude CLI not found; falling back")
        return _spawn_claude(repo, model)
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
        claude,
        "--append-system-prompt",
        prompt_body,
        "--model",
        model,
    ]
    info(f"running: herdr agent start {agent_name} -- {claude} --append-system-prompt <{prompt_path}> --model {model}")
    result = run_command(cmd, cwd=repo)
    if result.returncode != 0:
        info(
            f"herdr agent start failed (exit {result.returncode}); "
            f"falling back to direct claude"
        )
        return _spawn_claude(repo, model)
    info(f"herdr agent '{agent_name}' started in {worktree_path}")
    return result.returncode


def _spawn_claude(repo: Path, model: str) -> int:
    """Launch the `claude` CLI in the current repo (no herdr isolation)."""
    claude = resolve_executable("claude")
    if not claude:
        info("claude CLI not found on PATH; falling back to ollama run")
        return _spawn_ollama(repo, model)
    info(f"running: {claude} (cwd={repo})")
    result = run_command([claude], cwd=repo)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the model with the assembled system prompt.")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (auto-detected).")
    parser.add_argument(
        "--task",
        choices=("code", "review", "architecture", "documentation", "general"),
        default="general",
    )
    parser.add_argument("--model", default=None, help="Override the model name.")
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
        help="Which model runner to use. auto=prefer herdr if available, else claude, else ollama. none=print the prompt and stop.",
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
    model = resolve_model(args.model)
    info(f"model: {model}")

    backend = args.backend
    if backend == "auto":
        backend = "herdr" if _herdr_available() and resolve_executable("claude") else ("claude" if resolve_executable("claude") else "ollama")
        info(f"auto-selected backend: {backend}")

    if backend == "herdr":
        use_worktree = args.worktree == "yes" or (args.worktree == "auto" and _herdr_available())
        if use_worktree:
            return _spawn_herdr_agent(repo, prompt_path, model)
        return _spawn_claude(repo, model)
    if backend == "claude":
        return _spawn_claude(repo, model)
    if backend == "ollama":
        return _spawn_ollama(repo, model)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
