"""Implementation of the `agent-check` command.

Performs a lightweight validation of the repository: detects the stack,
verifies the .agent directory exists, checks for obvious missing files,
and prints a structured report.

If `firstmate` and/or `no-mistakes` are installed, the check is extended
with `firstmate doctor` (+ optional `firstmate build`) and
`no-mistakes check --all` so a single run covers project structure,
toolchain health, and pre-push validation.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import agent_doctor
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


def _check_firstmate(repo: Path, findings: list[tuple[str, str]]) -> None:
    if not agent_doctor.firstmate_present(repo):
        return
    rc, output = agent_doctor.run_doctor(repo)
    if rc == 127:
        findings.append(("warn", output.strip()))
        return
    if rc != 0:
        findings.append(("err", f"firstmate doctor failed (rc={rc})"))
    else:
        findings.append(("ok", "firstmate doctor passed"))
    for line in output.splitlines()[:20]:
        if line.strip():
            findings.append(("info", f"firstmate: {line.strip()[:120]}"))


def _check_firstmate_build(repo: Path, findings: list[tuple[str, str]]) -> None:
    if not agent_doctor.firstmate_present(repo):
        return
    rc, output = agent_doctor.run_build(repo)
    if rc == 127:
        return
    if rc != 0:
        findings.append(("warn", f"firstmate build failed (rc={rc})"))
    else:
        findings.append(("ok", "firstmate build passed"))


def _check_no_mistakes(repo: Path, findings: list[tuple[str, str]]) -> None:
    rc, output = agent_doctor.run_no_mistakes_check(repo)
    if rc == 127:
        return  # not installed, no message
    if rc != 0:
        findings.append(("err", f"no-mistakes check failed (rc={rc})"))
    else:
        findings.append(("ok", "no-mistakes check passed"))
    for line in output.splitlines()[:20]:
        if line.strip():
            findings.append(("info", f"no-mistakes: {line.strip()[:120]}"))


def run_check(repo: Path, *, with_firstmate: bool = True, with_no_mistakes: bool = True) -> int:
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

    if with_firstmate:
        _check_firstmate(repo, findings)
        _check_firstmate_build(repo, findings)
    if with_no_mistakes:
        _check_no_mistakes(repo, findings)

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
    parser.add_argument(
        "--no-firstmate",
        action="store_true",
        help="Skip firstmate doctor/build even if firstmate is installed.",
    )
    parser.add_argument(
        "--no-no-mistakes",
        action="store_true",
        help="Skip no-mistakes check even if no-mistakes is installed.",
    )
    args = parser.parse_args(argv)
    repo = (args.repo or find_repo_root()).resolve()
    info(f"checking {repo}")
    return run_check(
        repo,
        with_firstmate=not args.no_firstmate,
        with_no_mistakes=not args.no_no_mistakes,
    )


if __name__ == "__main__":
    raise SystemExit(main())
