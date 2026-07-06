"""Assemble the system prompt that will be sent to the model.

Order of layers (each extends the previous):

1. Global toolkit instructions (`AGENTS.md`).
2. Global agent prompt (`prompts/global-agent.md`).
3. Task-specific agent prompt (e.g. `prompts/coding-agent.md`).
4. Detected technology profile(s).
5. Project-specific instructions (`AGENTS.project.md`, `CLAUDE.md`, `docs/agent-rules/*.md`).
6. Generated repository summaries (`.agent/*.md`).
7. The user's task (appended at the end).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

from detect_stack import detect_stack
from scan_repo import AGENT_DIR_NAME
from utils import (
    DEFAULT_MODEL,
    find_repo_root,
    info,
    read_text,
    workbench_root,
)


PROJECT_INSTRUCTION_FILES = [
    "AGENTS.project.md",
    "CLAUDE.md",
]

TASK_AGENT_PROMPTS = {
    "code": "coding-agent.md",
    "review": "review-agent.md",
    "architecture": "architecture-agent.md",
    "documentation": "documentation-agent.md",
    "general": "global-agent.md",
}


def _section(title: str, body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    return f"## {title}\n\n{body}\n"


def _read_existing(paths: Iterable[Path]) -> list[tuple[Path, str]]:
    return [(p, read_text(p)) for p in paths if p.is_file()]


def collect_project_instructions(repo: Path) -> list[Path]:
    found: list[Path] = []
    for rel in PROJECT_INSTRUCTION_FILES:
        candidate = repo / rel
        if candidate.is_file():
            found.append(candidate)
    docs_rules = repo / "docs" / "agent-rules"
    if docs_rules.is_dir():
        for child in sorted(docs_rules.glob("*.md")):
            found.append(child)
    return found


# Files in `.agent/` that this module (and `agent_claude` /
# `agent_fleet`) produce and which must never be loaded back into a
# future prompt assembly. Including them would embed every previous
# prompt into every new prompt — a quadratic blow-up.
_SELF_PRODUCED_NAMES = {
    "SYSTEM_PROMPT.md",
    "SYSTEM_PROMPT.fleet.md",
    "fleet-index.txt",
}
_SELF_PRODUCED_GLOBS = ("SYSTEM_PROMPT.fleet-*.md",)


def _is_self_produced(path: Path) -> bool:
    if path.name in _SELF_PRODUCED_NAMES:
        return True
    return any(path.match(g) for g in _SELF_PRODUCED_GLOBS)


def collect_agent_summaries(repo: Path) -> list[Path]:
    out_dir = repo / AGENT_DIR_NAME
    if not out_dir.is_dir():
        return []
    return sorted(
        p for p in out_dir.glob("*.md")
        if p.is_file() and not _is_self_produced(p)
    )


def assemble_prompt(
    repo: Path,
    *,
    task: str = "general",
    extra_instructions: Optional[list[Path]] = None,
) -> tuple[str, list[Path]]:
    """Build the system prompt and return it alongside the list of files loaded."""
    wb = workbench_root()
    loaded: list[Path] = []

    parts: list[str] = []

    # 1. Global toolkit instructions.
    agents_md = wb / "AGENTS.md"
    if agents_md.is_file():
        parts.append(_section("Global toolkit instructions", read_text(agents_md)))
        loaded.append(agents_md)

    # 2. Task-specific agent prompt.
    prompt_filename = TASK_AGENT_PROMPTS.get(task, "global-agent.md")
    task_prompt = wb / "prompts" / prompt_filename
    if task_prompt.is_file():
        parts.append(_section("Agent role", read_text(task_prompt)))
        loaded.append(task_prompt)

    # 3. Detected technology profiles.
    matches = detect_stack(repo)
    for match in matches:
        body = read_text(match.profile_path)
        parts.append(_section(f"Profile: {match.name}", body))
        loaded.append(match.profile_path)

    # 4. Project-specific instructions.
    for path in collect_project_instructions(repo):
        parts.append(_section(f"Project rules: {path.name}", read_text(path)))
        loaded.append(path)

    # 5. Generated repository summaries.
    for path in collect_agent_summaries(repo):
        parts.append(_section(f"Repository summary: {path.name}", read_text(path)))
        loaded.append(path)

    # 6. Extra instructions passed by the caller.
    if extra_instructions:
        for path in extra_instructions:
            parts.append(_section(f"Extra: {path.name}", read_text(path)))
            loaded.append(path)

    body = "\n".join(p for p in parts if p)
    return body, loaded


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble a system prompt for the agent.")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (auto-detected).")
    parser.add_argument(
        "--task",
        choices=sorted(TASK_AGENT_PROMPTS),
        default="review",
        help="Which task-specific agent prompt to layer in. Default: review "
             "(matches the legacy `agent-review` shim; pass --task general to "
             "get the un-layered prompt).",
    )
    parser.add_argument(
        "--show-files",
        action="store_true",
        default=True,
        help="Print the list of files that were loaded to stderr. Default: on. "
             "Pass --no-show-files to suppress.",
    )
    parser.add_argument(
        "--no-show-files",
        dest="show_files",
        action="store_false",
        help="Suppress the loaded-files report that --show-files enables by default.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the prompt to this file instead of stdout.",
    )
    parser.add_argument(
        "task_text",
        nargs="?",
        default="",
        help="Optional task description to append to the prompt.",
    )
    args = parser.parse_args(argv)

    repo = (args.repo or find_repo_root()).resolve()
    body, loaded = assemble_prompt(repo, task=args.task)
    if args.task_text:
        body = body.rstrip() + "\n\n## Task\n\n" + args.task_text.strip() + "\n"
    if args.show_files:
        for path in loaded:
            info(f"loaded {path}")
    if args.output:
        args.output.write_text(body, encoding="utf-8")
        info(f"wrote {args.output}")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
