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


HELPERS = [
    "agent-init",
    "agent-scan",
    "agent-check",
    "agent-review",
    "agent-test",
    "agent-claude",
]


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


def _install_helpers(platform_name: str, *, force: bool) -> list[Path]:
    wb = workbench_root()
    shim_dir = wb / "scripts" / _shim_dir(platform_name)
    ext = _shim_extension(platform_name)
    target_dir = AGENT_BIN_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for name in HELPERS:
        source = shim_dir / f"{name}{ext}"
        if not source.is_file():
            info(f"skip: source missing {source}")
            continue
        target = target_dir / f"{name}{ext}"
        if target.exists() and not force:
            info(f"keep: {target} (use --force to overwrite)")
            installed.append(target)
            continue
        if _try_symlink(source, target):
            info(f"link: {target} -> {source}")
        else:
            shutil.copy2(source, target)
            if platform_name != "windows":
                target.chmod(0o755)
            info(f"copy: {target} <- {source}")
        installed.append(target)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
