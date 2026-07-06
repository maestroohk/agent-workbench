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
    """Report on the firstmate harness's install state.

    Previous behaviour called `firstmate doctor` and `firstmate build`,
    neither of which exists upstream; the call paths silently failed
    and the workbench never reported on firstmate. The new behaviour
    surfaces the harness install path and the most recent commit, and
    reports any `fm-bootstrap.sh` preflight output when available.
    """
    if not agent_doctor.firstmate_present(repo):
        findings.append(("info", "firstmate: not installed (run `agent-init --bootstrap=firstmate`)"))
        return
    version = agent_doctor.firstmate_version()
    harness = agent_doctor.FIRSTMATE_HARNESS_DIR
    if version:
        findings.append(("ok", f"firstmate: installed at {harness} ({version})"))
    else:
        findings.append(("ok", f"firstmate: installed at {harness}"))
    # The shim is what `agent-check` would actually call. Surface
    # whether it's resolvable on PATH.
    import shutil
    shim = shutil.which("firstmate")
    if shim:
        findings.append(("info", f"firstmate: shim on PATH at {shim}"))
    else:
        findings.append(("info", "firstmate: no shim on PATH (harness only); use `agent-init --bootstrap=firstmate` to install the shim"))

    # Best-effort: call firstmate doctor so users see the harness's
    # own preflight if it has one. Surface a clean info line on
    # non-zero so we don't claim a check that didn't run.
    rc, output = agent_doctor.run_doctor(repo)
    if rc == 0:
        for line in output.splitlines()[:10]:
            line = line.strip()
            if line:
                findings.append(("info", f"firstmate: {line[:120]}"))
    else:
        findings.append(("warn", f"firstmate doctor returned {rc}: {output.strip()[:120]}"))


def _check_firstmate_build(repo: Path, findings: list[tuple[str, str]]) -> None:
    """firstmate has no `build` subcommand; surface that explicitly."""
    if not agent_doctor.firstmate_present(repo):
        return
    rc, output = agent_doctor.run_build(repo)
    # run_build always returns rc=0 with a skip-message, so this branch
    # is informational only. Future-proof against upstream adding one.
    if output.strip():
        findings.append(("info", f"firstmate build: {output.strip()[:120]}"))


def _check_no_mistakes(repo: Path, findings: list[tuple[str, str]]) -> None:
    """Surface no-mistakes health and (if initialized) current-run status.

    We call `no-mistakes doctor` first (always available) and then
    `no-mistakes status` (only meaningful after `no-mistakes init`).
    The status call returns 127 with a clear message when the gate
    isn't set up; we swallow that and surface only the doctor output.
    """
    rc, output = agent_doctor.run_no_mistakes_doctor(repo)
    if rc == 127:
        return  # not installed, no message
    if rc != 0:
        findings.append(("warn", f"no-mistakes doctor reported issues (rc={rc})"))
    else:
        findings.append(("ok", "no-mistakes doctor passed"))
    for line in output.splitlines()[:20]:
        if line.strip():
            findings.append(("info", f"no-mistakes: {line.strip()[:120]}"))

    # Optional: surface the current-run status if the gate is initialized.
    rc, output = agent_doctor.run_no_mistakes_status(repo)
    if rc == 127:
        return
    if rc != 0:
        findings.append(("info", f"no-mistakes status (rc={rc})"))
    else:
        findings.append(("ok", "no-mistakes status: gate active"))


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
