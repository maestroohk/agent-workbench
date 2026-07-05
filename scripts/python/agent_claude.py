"""Implementation of the `agent-claude` launcher.

Builds the system prompt and prepares it for `ollama launch claude`. The
behaviour depends on the flags:

- With `--show-prompt`, prints the assembled prompt to stdout and exits.
- Without it, writes the prompt to `<repo>/.agent/SYSTEM_PROMPT.md` and then
  runs `ollama launch claude` from the repository root. Claude Code is
  expected to read its system instructions from `.agent/SYSTEM_PROMPT.md`
  (or you can copy-paste the prompt from the printed summary).

The default model is `minimax-m3:cloud`; override with `--model`,
`AGENT_MODEL`, or the `~/.agent-workbench/config.toml` file.
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


def launch_with_ollama(prompt_path: Path, model: str, repo: Path) -> int:
    """Invoke `ollama launch claude` from the repository root.

    The system prompt is already on disk at `prompt_path`. Claude Code is
    expected to read `.agent/SYSTEM_PROMPT.md` for system instructions.
    """
    ollama = first_executable(["ollama"])
    if not ollama:
        print("ollama executable not found on PATH", file=sys.stderr)
        print("install from https://ollama.com/download", file=sys.stderr)
        return 127
    info(f"system prompt: {prompt_path}")
    info(f"model: {model}")
    info(f"repo: {repo}")
    cmd = [ollama, "launch", "claude"]
    info(f"running: {' '.join(cmd)} (cwd={repo})")
    result = run_command(cmd, cwd=repo)
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
    model = resolve_model(args.model)
    return launch_with_ollama(prompt_path, model, repo)


if __name__ == "__main__":
    raise SystemExit(main())
