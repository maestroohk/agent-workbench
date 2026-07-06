"""Install or update agent-workbench on the current machine.

What this does:
- Detects the platform.
- Creates `<home>/.agent-workbench/` if missing.
- Symlinks (or copies, on Windows without privileges) the six helper scripts
  from `scripts/<shell>/` into `<home>/.local/bin/`.
- Prints a short report of what was done.

What this does NOT do:
- Modify the system PATH. The caller is responsible for ensuring that
  `<home>/.local/bin` is on PATH.
- Touch anything outside the user's home directory.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from utils import (
    AGENT_BIN_DIR,
    INSTALL_ROOT,
    detect_platform,
    info,
    workbench_root,
)

import bootstrap as _bootstrap


HELPERS = [
    "agent-init",
    "agent-scan",
    "agent-check",
    "agent-review",
    "agent-test",
    "agent-claude",
    "agent-bootstrap",
    "agent-fleet",
    "agent-go",
    "agent-overnight",
]


class _PathSentinel:
    """A stand-in for `Path | None` in lists, so callers can `.append(...)`
    unconditionally and we filter them out at the end. Avoids the pattern
    `installed.append(p) if p else None` cluttering the install loop."""
    __slots__ = ()


def _shim_dir(platform_name: str) -> str:
    return "powershell" if platform_name == "windows" else "bash"


def _shim_extension(platform_name: str) -> str:
    return ".ps1" if platform_name == "windows" else ""


def _try_symlink(source: Path, target: Path) -> bool:
    """Create a symlink. Return True on success, False if unsupported."""
    try:
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source)
        return True
    except (OSError, NotImplementedError):
        return False


def _install_one_shim(
    name: str,
    *,
    source: Path,
    target: Path,
    platform_name: str,
    force: bool,
) -> Path | None:
    """Symlink or copy one shim. Returns the target on success, None on skip."""
    if not source.is_file():
        info(f"skip: source missing {source}")
        return None
    if target.exists() and not force:
        info(f"keep: {target} (use --force to overwrite)")
        return target
    if _try_symlink(source, target):
        info(f"link: {target} -> {source}")
    else:
        shutil.copy2(source, target)
        if platform_name != "windows":
            target.chmod(0o755)
        info(f"copy: {target} <- {source}")
    return target


def _install_helpers(platform_name: str, *, force: bool) -> list[Path]:
    """Install the agent-* helper shims into ~/.local/bin/.

    On every platform we install two flavors:
    - The platform-native shims (powershell .ps1 on Windows, bash on unix).
      These are what the user runs from the platform's primary shell.
    - The bash shims (no extension). On unix this is the same flavor as
      the platform-native one (no-op duplicate); on Windows it gives Git
      Bash / WSL users a stable `agent-init`, `agent-go`, ... invocation
      without needing to install a separate PowerShell profile.

    The previous behavior installed only the platform-native flavor,
    which left Windows + Git Bash users without a working `agent-init`
    in their shell.
    """
    wb = workbench_root()
    native_dir = wb / "scripts" / _shim_dir(platform_name)
    native_ext = _shim_extension(platform_name)
    target_dir = AGENT_BIN_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []

    for name in HELPERS:
        # Native shim.
        installed.append(_install_one_shim(
            name,
            source=native_dir / f"{name}{native_ext}",
            target=target_dir / f"{name}{native_ext}",
            platform_name=platform_name,
            force=force,
        ) or _PathSentinel())
        # Bash shim — always install alongside, on every platform. On
        # Windows this gives Git Bash / WSL users a stable
        # `agent-init`, `agent-go`, ... invocation. The shim is a thin
        # wrapper that resolves the toolkit root via the marker file
        # the installer writes, then dispatches to the platform's
        # agent.sh (which already handles Python resolution on its
        # platform). The Windows caveat: agent.sh's `command -v python`
        # may be hijacked by the Microsoft Store App Execution Alias
        # on some Windows + Git Bash setups, so the bash shim first
        # tries the PowerShell wrapper (which already finds python via
        # the registry) and only falls back to agent.sh if PowerShell
        # is unavailable.
        if native_ext == ".ps1":
            bash_target = target_dir / name
            if bash_target.exists() and not force:
                info(f"keep: {bash_target} (use --force to overwrite)")
                installed.append(bash_target)
            else:
                verb = name.replace("agent-", "")
                # On Windows, prefer the PowerShell wrapper so we use
                # its vetted python resolution. On unix, dispatch
                # directly to agent.sh.
                if platform_name == "windows":
                    shim_body = (
                        "#!/usr/bin/env bash\n"
                        "# Auto-generated bash shim for the\n"
                        "# agent-workbench helper on Windows. Delegates to\n"
                        "# the PowerShell wrapper of the same name, which\n"
                        "# already handles the python interpreter lookup\n"
                        "# (the Windows App Execution Alias can hijack a\n"
                        "# bare `python` call from a non-MSYS shell, so we\n"
                        "# avoid the issue by going through PowerShell).\n"
                        f'ps_exe=""\n'
                        f'for n in powershell.exe pwsh.exe powershell pwsh; do\n'
                        f'  if command -v "$n" >/dev/null 2>&1; then ps_exe="$n"; break; fi\n'
                        f'done\n'
                        f'if [ -z "$ps_exe" ]; then\n'
                        f'  echo "agent-workbench: no powershell/pwsh on PATH; cannot run {name}" >&2\n'
                        f'  exit 127\n'
                        f'fi\n'
                        f'exec "$ps_exe" -NoProfile -ExecutionPolicy Bypass -File "$HOME/.local/bin/{name}.ps1" "$@"\n'
                    )
                else:
                    shim_body = (
                        "#!/usr/bin/env bash\n"
                        "# Auto-generated bash shim for the\n"
                        "# agent-workbench helper. Resolves the toolkit\n"
                        "# root via ~/.local/bin/agent-workbench-home\n"
                        "# and dispatches to scripts/bash/agent.sh.\n"
                        f'_aw_home="$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"\n'
                        f'_aw_marker="${{_aw_home}}/agent-workbench-home"\n'
                        f'if [ -f "${{_aw_marker}}" ]; then\n'
                        f'  _aw_root="$(cat "${{_aw_marker}}")"\n'
                        f'  exec "${{_aw_root}}/scripts/bash/agent.sh" {verb} "$@"\n'
                        f'else\n'
                        f'  echo "agent-workbench: marker not found at ${{_aw_marker}}; re-run agent-init" >&2\n'
                        f'  exit 127\n'
                        f'fi\n'
                    )
                bash_target.write_text(shim_body, encoding="utf-8")
                bash_target.chmod(0o755)
                info(f"copy: {bash_target} (generated bash shim)")
                installed.append(bash_target)

    # Drop the None sentinels.
    installed = [p for p in installed if not isinstance(p, _PathSentinel)]

    # Write a marker file alongside the installed shims so the PowerShell
    # wrappers can find the toolkit root when run from `~/.local/bin/`.
    marker = target_dir / "agent-workbench-home"
    try:
        marker.write_text(str(wb), encoding="utf-8")
        info(f"marker: {marker} -> {wb}")
    except OSError as exc:
        info(f"could not write marker {marker}: {exc}")
    return installed


def _ensure_install_root() -> Path:
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    return INSTALL_ROOT


def _print_path_hint(platform_name: str) -> None:
    if str(AGENT_BIN_DIR) in (os.environ.get("PATH") or "").split(os.pathsep):
        info(f"{AGENT_BIN_DIR} is already on PATH")
        return
    info(f"add {AGENT_BIN_DIR} to your PATH to use the helpers globally")
    if platform_name == "windows":
        info("PowerShell: $env:Path = \"$env:USERPROFILE\\.local\\bin;$env:Path\"")
    else:
        info("bash: export PATH=\"$HOME/.local/bin:$PATH\"")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or update agent-workbench.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing helpers.")
    parser.add_argument("--print-platform", action="store_true", help="Print detected platform and exit.")
    bootstrap_group = parser.add_mutually_exclusive_group()
    bootstrap_group.add_argument(
        "--bootstrap",
        default=None,
        metavar="LIST",
        help="Comma-separated list of external tools to install after symlinking. "
             "Default: herdr,firstmate,no-mistakes,treehouse. Pass 'all' for the full table.",
    )
    bootstrap_group.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="Skip the external-tool install step (only install the workbench's own helpers).",
    )
    parser.add_argument(
        "--no-curl",
        action="store_true",
        help="Skip install methods that pipe a remote shell (winget/choco/brew/git only).",
    )
    args = parser.parse_args(argv)

    platform_name = detect_platform()
    if args.print_platform:
        print(platform_name)
        return 0

    info(f"platform: {platform_name}")
    _ensure_install_root()
    installed = _install_helpers(platform_name, force=args.force)
    _print_path_hint(platform_name)
    info(f"installed {len(installed)} helper(s)")

    if not args.no_bootstrap:
        if args.bootstrap is None:
            targets: list[str] | None = None
        elif args.bootstrap.strip().lower() == "all":
            targets = list(_bootstrap.DEPENDENCIES)
        else:
            targets = [t.strip() for t in args.bootstrap.split(",") if t.strip()]
        info(f"bootstrapping: {','.join(targets) if targets else '(defaults)'}")
        statuses = _bootstrap.install_dependencies(targets, allow_curl=not args.no_curl)
        missing = [s.name for s in statuses if not s.present]
        if missing:
            info(f"could not bootstrap: {', '.join(missing)} — re-run with --no-bootstrap to skip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
