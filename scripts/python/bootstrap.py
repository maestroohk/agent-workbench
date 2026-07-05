"""Auto-install the external tools the workbench depends on.

`agent-init` calls into here after symlinking the helper scripts, so a
clean machine can end up with the full toolchain (herdr, firstmate,
no-mistakes, treehouse, gnhf, ollama, wezterm) on PATH in one run.

Design:
- Each dependency is a small table entry describing how to probe for it
  and how to install it on each platform.
- The installer tries package managers first (winget, choco, brew, npm),
  then the project's official one-liner (curl-piped shell), then a
  git-clone fallback.
- The user controls the scope: `--bootstrap=herdr,firstmate` or
  `--no-bootstrap` to skip the step entirely.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from utils import detect_platform, first_executable, info, run_command


# --- Dependency table -----------------------------------------------------
# Each entry maps a logical name to: a probe (the binary to look for on
# PATH), a one-line purpose, and an ordered list of install methods tried
# in sequence. The first method that succeeds wins. The probe check is
# `shutil.which(probe)` — if found, the tool is considered present and
# the install is skipped.

DEPENDENCIES: dict[str, dict] = {
    "wezterm": {
        "probe": "wezterm",
        "purpose": "GPU-accelerated terminal (fallback when herdr's own mux is unwanted).",
        "install": [
            {"windows": ["winget", "install", "--id", "wez.wezterm", "-e", "--accept-source-agreements", "--accept-package-agreements"]},
            {"windows": ["choco", "install", "-y", "wezterm"]},
            {"darwin": ["brew", "install", "--cask", "wezterm"]},
            {"linux": ["sh", "-c", "curl -fsSL https://wezfurlong.org/wezterm/wezterm.AppImage -o ~/.local/bin/wezterm && chmod +x ~/.local/bin/wezterm"]},
        ],
    },
    "herdr": {
        "probe": "herdr",
        "purpose": "Agent multiplexer (default backend for agent-fleet).",
        "install": [
            {"windows": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://herdr.dev/install.ps1 | iex"]},
            {"darwin": ["sh", "-c", "curl -fsSL https://herdr.dev/install.sh | sh"]},
            {"linux": ["sh", "-c", "curl -fsSL https://herdr.dev/install.sh | sh"]},
        ],
    },
    "firstmate": {
        "probe": "claude",  # firstmate is a directory + AGENTS.md harness; presence is best probed via the claude CLI it drives
        "purpose": "Per-project command orchestrator (firstmate test / build / lint). Clone github.com/kunchenguid/firstmate.",
        "install": [
            {"any": ["git", "clone", "https://github.com/kunchenguid/firstmate.git", "${HOME}/firstmate"]},
        ],
        "presence_hint": "${HOME}/firstmate/AGENTS.md",
    },
    "no-mistakes": {
        "probe": "no-mistakes",
        "purpose": "Git proxy that pre-validates with review/test/docs/lint before pushing.",
        "install": [
            {"windows": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.ps1 | iex"]},
            {"darwin": ["sh", "-c", "curl -fsSL https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh | sh"]},
            {"linux": ["sh", "-c", "curl -fsSL https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh | sh"]},
        ],
    },
    "treehouse": {
        "probe": "treehouse",
        "purpose": "Git worktree pool — gives agent-fleet N isolated worktrees fast.",
        "install": [
            {"windows": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://kunchenguid.github.io/treehouse/install.ps1 | iex"]},
            {"darwin": ["sh", "-c", "curl -fsSL https://kunchenguid.github.io/treehouse/install.sh | sh"]},
            {"linux": ["sh", "-c", "curl -fsSL https://kunchenguid.github.io/treehouse/install.sh | sh"]},
        ],
    },
    "gnhf": {
        "probe": "gnhf",
        "purpose": "Overnight autonomous agent runner.",
        "install": [
            {"any": ["npm", "install", "-g", "gnhf"]},
        ],
    },
    "ollama": {
        "probe": "ollama",
        "purpose": "Local model runtime (fallback when the `claude` CLI is not available).",
        "install": [
            {"windows": ["winget", "install", "--id", "Ollama.Ollama", "-e", "--accept-source-agreements", "--accept-package-agreements"]},
            {"windows": ["choco", "install", "-y", "ollama"]},
            {"darwin": ["brew", "install", "ollama"]},
            {"linux": ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]},
        ],
    },
    "claude": {
        "probe": "claude",
        "purpose": "Anthropic Claude Code CLI. The actual agent runtime for agent-claude and agent-fleet.",
        "install": [
            {"any": ["npm", "install", "-g", "@anthropic-ai/claude-code"]},
        ],
    },
}


DEFAULT_BOOTSTRAP_SET = ("herdr", "firstmate", "no-mistakes", "treehouse")


# --- Public API -----------------------------------------------------------

@dataclass
class DependencyStatus:
    name: str
    purpose: str
    present: bool
    path: Optional[str] = None
    version: Optional[str] = None
    installed_by: Optional[str] = None  # which method succeeded, if any
    error: Optional[str] = None


def _version_of(probe: str) -> Optional[str]:
    """Return a short version string for a tool, or None if unknown.

    Tries `--version`, `-V`, and `-v` in sequence because each tool picks
    its own convention (wezterm, herdr, claude use one; ollama rejects
    `--version` and `-V` but accepts `-v`; npm uses `-v`; etc.).
    """
    flag_attempts: list[tuple[list[str], ...]] = [
        ([probe, "--version"],),
        ([probe, "-V"],),
        ([probe, "-v"],),
        ([probe, "version"],),
    ]
    for (cmd,) in flag_attempts:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            continue
        text = (result.stdout or result.stderr or "").strip()
        if not text:
            continue
        # Skip error messages masquerading as version output.
        if "unknown shorthand flag" in text.lower() or "unrecognized" in text.lower():
            continue
        first = text.splitlines()[0].strip()
        if not first:
            continue
        return first[:120]
    return None


def _presence_hint_satisfied(hint: str) -> bool:
    """Expand `${HOME}`-style placeholders in a presence_hint and check the file exists."""
    expanded = os.path.expandvars(hint)
    return Path(expanded).is_file()


def check_dependencies(names: Optional[list[str]] = None) -> list[DependencyStatus]:
    """Probe every dependency and report its status. Does not install."""
    selected = names or list(DEPENDENCIES)
    statuses: list[DependencyStatus] = []
    for name in selected:
        dep = DEPENDENCIES.get(name)
        if not dep:
            statuses.append(DependencyStatus(name=name, purpose="(unknown)", present=False, error="no such dependency"))
            continue
        path = shutil.which(dep["probe"])
        hint = dep.get("presence_hint")
        present = bool(path) or (bool(hint) and _presence_hint_satisfied(hint))
        statuses.append(
            DependencyStatus(
                name=name,
                purpose=dep["purpose"],
                present=present,
                path=path,
                version=_version_of(dep["probe"]) if path else None,
            )
        )
    return statuses


def _matches_platform(method: dict, platform_name: str) -> bool:
    """A method matches if it has an entry for this platform, or an 'any' key."""
    if "any" in method:
        return True
    if "windows" in method and platform_name in ("windows", "wsl"):
        return True
    if "darwin" in method and platform_name == "darwin":
        return True
    if "linux" in method and platform_name == "linux":
        return True
    return False


def _run_method(method_args: list[str]) -> tuple[bool, str]:
    """Run one install method. Return (ok, output)."""
    expanded = [os.path.expandvars(a) for a in method_args]
    info(f"trying: {' '.join(expanded[:3])}…")
    result = subprocess.run(expanded, capture_output=True, text=True)
    combined = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, combined[:500]


def install_dependency(name: str, *, platform_name: Optional[str] = None) -> DependencyStatus:
    """Install one dependency, trying each method in order. Idempotent."""
    dep = DEPENDENCIES.get(name)
    if not dep:
        return DependencyStatus(name=name, purpose="(unknown)", present=False, error="no such dependency")

    # Already present? Skip.
    current = check_dependencies([name])[0]
    if current.present:
        info(f"{name}: already present at {current.path or dep.get('presence_hint')}")
        current.installed_by = "(already installed)"
        return current

    platform_name = platform_name or detect_platform()
    last_error = ""
    for method in dep["install"]:
        if not _matches_platform(method, platform_name):
            continue
        for key, args in method.items():
            if key == "any" or _matches_platform({key: args}, platform_name):
                ok, output = _run_method(args)
                if ok:
                    after = check_dependencies([name])[0]
                    after.installed_by = f"{key}: {args[0] if args else '?'}"
                    if after.present:
                        info(f"{name}: installed via {after.installed_by}")
                        return after
                    last_error = f"{args[0]} exit 0 but {name} still not on PATH ({output[:120]})"
                else:
                    last_error = f"{args[0] if args else '?'} failed: {output[:200]}"
    return DependencyStatus(
        name=name,
        purpose=dep["purpose"],
        present=False,
        error=last_error or f"no install method matched platform {platform_name}",
    )


def install_dependencies(names: Optional[list[str]] = None, *, allow_curl: bool = True) -> list[DependencyStatus]:
    """Install each dependency in the list. Returns the final status of each."""
    selected = names or list(DEFAULT_BOOTSTRAP_SET)
    platform_name = detect_platform()
    info(f"bootstrap platform: {platform_name}")
    results: list[DependencyStatus] = []
    for name in selected:
        if name not in DEPENDENCIES:
            results.append(DependencyStatus(name=name, purpose="(unknown)", present=False, error="no such dependency"))
            continue
        if not allow_curl:
            # Skip methods that pipe to a remote shell.
            dep = DEPENDENCIES[name]
            dep["install"] = [
                m for m in dep["install"]
                if not any("curl" in (a if isinstance(a, str) else "") or "irm" in (a if isinstance(a, str) else "") for v in m.values() for a in v)
            ]
        results.append(install_dependency(name, platform_name=platform_name))
    return results


# --- CLI ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the external tools the workbench depends on.")
    parser.add_argument(
        "--only",
        default=",".join(DEFAULT_BOOTSTRAP_SET),
        help=f"Comma-separated list of dependencies to install (default: {','.join(DEFAULT_BOOTSTRAP_SET)}). "
             f"Available: {','.join(DEPENDENCIES)}",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Install every dependency in the table, not just the default set.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check status; do not install.",
    )
    parser.add_argument(
        "--no-curl",
        action="store_true",
        help="Skip methods that pipe a remote shell (winget/choco/brew/git only).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    if args.all:
        names: Optional[list[str]] = list(DEPENDENCIES)
    elif args.only:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
    else:
        names = list(DEFAULT_BOOTSTRAP_SET)

    if args.check:
        statuses = check_dependencies(names)
    else:
        statuses = install_dependencies(names, allow_curl=not args.no_curl)

    if args.json:
        payload = [
            {
                "name": s.name,
                "purpose": s.purpose,
                "present": s.present,
                "path": s.path,
                "version": s.version,
                "installed_by": s.installed_by,
                "error": s.error,
            }
            for s in statuses
        ]
        print(json.dumps(payload, indent=2))
    else:
        print(f"{'name':<14} {'present':<8} path / version")
        print("-" * 72)
        any_missing = False
        for s in statuses:
            mark = "yes" if s.present else "NO"
            line = f"{s.name:<14} {mark:<8} {s.path or ''}"
            if s.version:
                line += f"  ({s.version})"
            elif s.error:
                line += f"  error: {s.error}"
            print(line)
            if not s.present:
                any_missing = True
        if any_missing and not args.check:
            print()
            print("Some dependencies could not be installed. Re-run with --json to see details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
