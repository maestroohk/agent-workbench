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
            # Real install: download the latest release asset from GitHub
            # and extract the binary into ~/.local/bin/.
            {"any": ["_github_release", "kunchenguid/no-mistakes", "no-mistakes"]},
        ],
    },
    "treehouse": {
        "probe": "treehouse",
        "purpose": "Git worktree pool — gives agent-fleet N isolated worktrees fast.",
        "install": [
            {"any": ["_github_release", "kunchenguid/treehouse", "treehouse"]},
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


# Per-install-method timeout. The herdr / no-mistakes / treehouse
# installers each download a multi-MB archive; default 180s is generous
# on slow connections and tight enough to fail fast on a dead URL.
_DEFAULT_INSTALL_TIMEOUT = 180


def _resolve_powershell() -> Optional[str]:
    """Pick the best PowerShell binary on Windows: pwsh (7+) before powershell (5.1).

    pwsh handles some command-line quoting better and is what the modern
    installer scripts target. Returns the absolute path or None.
    """
    if os.name != "nt":
        return None
    for name in ("pwsh.exe", "pwsh", "powershell.exe", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _run_method(method_args: list[str], *, timeout: int = _DEFAULT_INSTALL_TIMEOUT) -> tuple[bool, str]:
    """Run one install method. Return (ok, output).

    Robust against:
    - Executable missing on PATH (`FileNotFoundError`) — returns ok=False.
    - Hung download — `timeout` aborts the subprocess.
    - Non-zero exit from the installer script — already handled via returncode.
    - The first argv element being a bare `powershell` on Windows — we
      resolve it to a full path so `CreateProcess` never has to guess.
    - The first element being a sentinel like `"_github_release"` — we
      handle it in-process by downloading the latest release binary.
    """
    expanded = [os.path.expandvars(a) for a in method_args]
    # Sentinel: download the latest release binary from GitHub and place
    # it in ~/.local/bin. Used for no-mistakes and treehouse (both
    # publish release zips/tarballs on GitHub Releases).
    if expanded and expanded[0] == "_github_release":
        if len(expanded) < 3:
            return False, "_github_release needs <repo> <binary_name>"
        repo = expanded[1]
        binary_name = expanded[2]
        return _install_from_github_release(repo, binary_name, timeout=timeout)
    # On Windows, prefer pwsh over powershell and resolve to a full path
    # so the subprocess can always find the interpreter.
    if expanded and expanded[0].lower() in ("powershell", "powershell.exe", "pwsh", "pwsh.exe"):
        full = _resolve_powershell()
        if full:
            expanded[0] = full
        else:
            return False, "powershell/pwsh not on PATH; cannot run Windows installer"
    info(f"trying: {' '.join(expanded[:3])}…")
    try:
        result = subprocess.run(expanded, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        return False, f"executable not found: {expanded[0]} ({exc})"
    except subprocess.TimeoutExpired as exc:
        return False, f"timed out after {timeout}s: {' '.join(expanded[:3])}…"
    except OSError as exc:
        return False, f"OSError: {exc}"
    combined = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, combined[:500]


# --- GitHub release install ----------------------------------------------

def _detect_platform_asset_suffix() -> tuple[str, str, str]:
    """Return (asset_os, asset_arch, archive_ext) for picking a release asset.

    Maps the workbench's platform names to the suffixes used by the
    kunchenguid release pipeline. e.g. on a Windows x86_64 box this
    returns ('windows', 'amd64', 'zip'); on Linux arm64 it's
    ('linux', 'arm64', 'tar.gz').
    """
    sysname = sys.platform
    machine = (os.environ.get("PROCESSOR_ARCHITECTURE") or "").lower()
    if sysname.startswith("win"):
        os_part = "windows"
        ext = "zip"
    elif sysname == "darwin":
        os_part = "darwin"
        ext = "tar.gz"
    else:
        os_part = "linux"
        ext = "tar.gz"
    if machine in ("amd64", "x86_64", "x64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine or "amd64"
    return os_part, arch, ext


def _install_from_github_release(repo: str, binary_name: str, *, timeout: int = _DEFAULT_INSTALL_TIMEOUT) -> tuple[bool, str]:
    """Download the latest release binary for `repo` and place it in ~/.local/bin.

    Picks the right asset for the current platform/arch, downloads it to
    a temp file, extracts the binary, and writes it to
    `<AGENT_BIN_DIR>/<binary_name>[.exe]`. The asset name convention is
    `<binary_name>-<version>-<os>-<arch>.<ext>` (matching the
    kunchenguid release pipeline for no-mistakes and treehouse).
    """
    # AGENT_BIN_DIR is defined in utils; import here to avoid a circular
    # import at module load (utils imports nothing from bootstrap).
    from utils import AGENT_BIN_DIR

    os_part, arch, ext = _detect_platform_asset_suffix()
    info(f"{binary_name}: resolving latest release for {repo} on {os_part}/{arch}")

    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        import urllib.request
        req = urllib.request.Request(api_url, headers={"User-Agent": "agent-workbench-bootstrap"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — network/GitHub can fail in many ways
        return False, f"failed to query {api_url}: {exc}"

    tag = release.get("tag_name") or "v0.0.0"
    # Asset name pattern (kunchenguid release pipeline):
    #   <binary_name>-<tag>-<os>-<arch>.<ext>
    # e.g. no-mistakes-v1.31.2-windows-amd64.zip
    #      treehouse-v2.0.0-darwin-arm64.tar.gz
    asset_name = f"{binary_name}-{tag}-{os_part}-{arch}.{ext}"
    download_url = None
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            download_url = asset.get("browser_download_url")
            break
    if not download_url:
        # Fallback: tag without leading "v".
        bare = f"{binary_name}-{tag.lstrip('v')}-{os_part}-{arch}.{ext}"
        for asset in release.get("assets", []):
            if asset.get("name") == bare:
                download_url = asset.get("browser_download_url")
                asset_name = bare
                break
    if not download_url:
        names = [a.get("name") for a in release.get("assets", [])]
        return False, f"no asset matching {asset_name} in {repo}@{tag} (have: {names[:6]})"

    info(f"{binary_name}: downloading {asset_name}")
    try:
        import tempfile, zipfile, tarfile
        with urllib.request.urlopen(download_url, timeout=timeout) as resp:
            data = resp.read()
    except Exception as exc:
        return False, f"download failed: {download_url}: {exc}"

    AGENT_BIN_DIR.mkdir(parents=True, exist_ok=True)
    binary_path = AGENT_BIN_DIR / (binary_name + (".exe" if os_part == "windows" else ""))
    try:
        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        if ext == "zip":
            with zipfile.ZipFile(tmp_path, "r") as zf:
                member = None
                for name in zf.namelist():
                    base = name.rsplit("/", 1)[-1]
                    if base == binary_name + ".exe" or base == binary_name:
                        member = name
                        break
                if member is None:
                    return False, f"no {binary_name} inside the zip (members: {zf.namelist()[:6]})"
                with zf.open(member) as src, binary_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        else:
            with tarfile.open(tmp_path, "r:gz") as tf:
                member = None
                for tarinfo in tf.getmembers():
                    base = tarinfo.name.rsplit("/", 1)[-1]
                    if base == binary_name:
                        member = tarinfo
                        break
                if member is None:
                    return False, f"no {binary_name} inside the tarball"
                with tf.extractfile(member) as src, binary_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        tmp_path.unlink(missing_ok=True)
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
        return False, f"extract failed: {exc}"

    if os_part != "windows":
        binary_path.chmod(0o755)
    info(f"{binary_name}: installed at {binary_path}")
    return True, f"installed {binary_name} {tag} from {repo}@{tag}"


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
        # Defensive: an unexpected exception in one tool's install must
        # not crash the whole bootstrap. The remaining tools still get
        # their turn, and the user sees a clear per-tool error.
        try:
            results.append(install_dependency(name, platform_name=platform_name))
        except Exception as exc:  # noqa: BLE001 — we want to keep going
            results.append(DependencyStatus(
                name=name,
                purpose=DEPENDENCIES[name]["purpose"],
                present=False,
                error=f"unexpected error: {type(exc).__name__}: {exc}",
            ))
            info(f"{name}: unexpected error {type(exc).__name__}: {exc}")
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
