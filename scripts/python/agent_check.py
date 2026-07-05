"""Implementation of the `agent-check` command.

Performs a lightweight validation of the repository: detects the stack,
verifies the .agent directory exists, checks for obvious missing files,
and prints a structured report.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from detect_stack import detect_stack
from scan_repo import AGENT_DIR_NAME, SUMMARIES
from utils import die, find_repo_root, info


def _check_agent_dir(repo: Path) -> list[str]:
    out_dir = repo / AGENT_DIR_NAME
    if not out_dir.is_dir():
        return [f"missing {AGENT_DIR_NAME}/ -- run `agent-scan` to generate it"]
    missing = [name for name in SUMMARIES if not (out_dir / name).is_file()]
    if missing:
        return [f"{AGENT_DIR_NAME}/{name} is missing -- re-run `agent-scan`" for name in missing]
    return []


def _check_project_rules(repo: Path) -> list[str]:
    found: list[str] = []
    for name in ("AGENTS.project.md", "CLAUDE.md", "README.md"):
        if (repo / name).is_file():
            found.append(name)
    if not found:
        return ["no project instructions found (AGENTS.project.md or CLAUDE.md)"]
    return [f"project instruction: {name}" for name in found]


def _check_no_secrets(repo: Path) -> list[str]:
    issues: list[str] = []
    for name in (".env", "credentials.json", "service-account.json"):
        candidate = repo / name
        if candidate.is_file():
            issues.append(f"potentially committed secret file: {name}")
    return issues


def run_check(repo: Path) -> int:
    findings: list[tuple[str, str]] = []
    matches = detect_stack(repo)
    if not matches:
        findings.append(("warn", "no technology profiles matched"))
    else:
        for m in matches:
            findings.append(("ok", f"profile: {m.name} ({len(m.evidence)} markers)"))

    for issue in _check_agent_dir(repo):
        findings.append(("error", issue))
    for note in _check_project_rules(repo):
        findings.append(("info", note))
    for issue in _check_no_secrets(repo):
        findings.append(("warn", issue))

    has_error = False
    for level, message in findings:
        marker = {"ok": "[ok]", "info": "[info]", "warn": "[warn]", "error": "[err]"}[level]
        print(f"  {marker} {message}")
        if level == "error":
            has_error = True

    print()
    if has_error:
        print("check failed")
        return 1
    print("check passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the current repository.")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (auto-detected).")
    args = parser.parse_args(argv)
    repo = (args.repo or find_repo_root()).resolve()
    info(f"checking {repo}")
    return run_check(repo)


if __name__ == "__main__":
    raise SystemExit(main())
