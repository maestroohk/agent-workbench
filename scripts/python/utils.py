"""Shared utilities for agent-workbench.

Single source of truth for all business logic. Bash and PowerShell wrappers
must delegate to these functions, never duplicate them.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_MODEL = "minimax-m3:cloud"
AGENT_BIN_DIR = Path(
    os.environ.get("AGENT_WORKBENCH_BIN")
    or (Path.home() / ".local" / "bin")
)
INSTALL_ROOT = Path(
    os.environ.get("AGENT_WORKBENCH_HOME")
    or (Path.home() / ".agent-workbench")
)
REPO_ROOT_OVERRIDE = os.environ.get("AGENT_WORKBENCH_REPO")


@dataclass
class CommandResult:
    """Result of a subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def combined(self) -> str:
        return f"{self.stdout}{self.stderr}"


@dataclass
class StackMatch:
    """A single detected technology profile for a repository."""

    name: str
    profile_path: Path
    evidence: list[str] = field(default_factory=list)


def die(message: str, code: int = 1) -> "None":
    """Print an error and exit."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def info(message: str) -> None:
    """Print an informational line to stderr (so stdout stays scriptable)."""
    print(f"agent-workbench: {message}", file=sys.stderr)


def detect_platform() -> str:
    """Return one of: linux, darwin, windows, wsl."""
    system = platform.system().lower()
    if system == "linux":
        try:
            with open("/proc/version", "r", encoding="utf-8") as handle:
                if "microsoft" in handle.read().lower() or "wsl" in handle.read().lower():
                    return "wsl"
        except OSError:
            pass
        return "linux"
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "windows"
    return system


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Locate the repository root by walking upward looking for markers.

    Markers: `.git`, `AGENTS.project.md`, `CLAUDE.md`, or any of the
    technology-specific manifest files recognised by `detect_stack`.
    """
    start = Path(start or REPO_ROOT_OVERRIDE or Path.cwd()).resolve()
    markers = {
        ".git",
        "AGENTS.project.md",
        "CLAUDE.md",
    }
    candidate = start
    for parent in [candidate, *candidate.parents]:
        try:
            entries = {p.name for p in parent.iterdir()}
        except OSError:
            continue
        if entries & markers:
            return parent
        # Treat the existence of any of these top-level files as a repo root.
        tech_markers = {
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "Pipfile",
            "setup.py",
            "setup.cfg",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "angular.json",
            "docker-compose.yml",
            "docker-compose.yaml",
            "Dockerfile",
        }
        if entries & tech_markers:
            return parent
    # Fall back to the starting directory; the caller may still get value.
    return start


def workbench_root() -> Path:
    """Return the path to the agent-workbench source tree.

    Resolution order:
    1. `AGENT_WORKBENCH_HOME` if it contains an `AGENTS.md` file.
    2. The parent of this `utils.py` file (the cloned repository).
    """
    env_root = os.environ.get("AGENT_WORKBENCH_HOME")
    if env_root:
        candidate = Path(env_root).resolve()
        if (candidate / "AGENTS.md").is_file():
            return candidate
    return Path(__file__).resolve().parent.parent.parent


def read_text(path: Path) -> str:
    """Read a file as UTF-8, returning an empty string on missing files."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def read_text_files(paths: Iterable[Path]) -> list[str]:
    """Read each path; return only the contents of existing files."""
    return [read_text(p) for p in paths if p.is_file()]


def write_text(path: Path, content: str) -> None:
    """Write content to path, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_command(
    args: list[str],
    *,
    cwd: Optional[Path] = None,
    timeout: Optional[int] = None,
    check: bool = False,
) -> CommandResult:
    """Run a command and capture its output. Never raise on non-zero exit."""
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(returncode=127, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\n[timeout after {timeout}s]",
        )
    if check and completed.returncode != 0:
        die(
            f"command failed: {' '.join(args)}\n{completed.stderr or completed.stdout}",
            code=completed.returncode,
        )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def list_subdirectories(root: Path, *, max_depth: int = 3) -> list[Path]:
    """Return subdirectories of `root` up to `max_depth` levels deep."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    for current, dirs, _ in os.walk(root):
        rel = Path(current).relative_to(root)
        depth = 0 if rel == Path(".") else len(rel.parts)
        if depth > max_depth:
            dirs[:] = []
            continue
        if rel != Path("."):
            found.append(Path(current))
    return found


def truncate(text: str, limit: int = 4000) -> str:
    """Truncate text to `limit` characters with a marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... truncated, {len(text) - limit} more characters]"


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Parse a simple YAML-ish front matter block from the top of a Markdown file.

    Only the flat `key: value` lines between `---` fences are recognised.
    Anything more complex would be over-engineering for a profile file.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text
    meta: dict = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    body = "\n".join(lines[end + 1 :])
    return meta, body


def ensure_on_path(bin_dir: Path) -> None:
    """Add `bin_dir` to the current process's PATH for the duration of the run."""
    bin_dir = bin_dir.resolve()
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep)
    if str(bin_dir) not in parts:
        os.environ["PATH"] = os.pathsep.join([str(bin_dir), *parts])


def first_executable(candidates: list[str]) -> Optional[str]:
    """Return the first candidate that resolves to an executable on PATH."""
    for name in candidates:
        resolved = resolve_executable(name)
        if resolved:
            return resolved
    return None


# On Windows, `shutil.which(name)` returns the first PATH match, which
# for npm-installed tools (claude, gnhf) is the bare Node.js shim — a
# `.cmd`/`.bat` shim script, not a PE binary. `CreateProcessW` rejects
# those with `WinError 193: %1 is not a valid Win32 application`, so
# the caller's `subprocess.run` blows up. The fix is to look for the
# Windows-executable forms explicitly and prefer them. Order matters:
# `.cmd` / `.bat` are checked before `.exe` because most npm-published
# CLIs ship a `.cmd` entry point and no `.exe`.
_WINDOWS_EXECUTABLE_SUFFIXES = (".cmd", ".bat", ".exe")


def resolve_executable(name: str) -> Optional[str]:
    """Resolve `name` to an executable path on this platform.

    On Windows, prefers `name.cmd` / `name.bat` / `name.exe` over the
    bare shim so `subprocess.run` does not hit `WinError 193`. On
    non-Windows, returns `shutil.which(name)` unchanged.

    If `name` already carries a Windows suffix (e.g. "claude.cmd"),
    that suffix is tried first; the rest of the order is the same.
    """
    if os.name == "nt":
        # On Windows, `shutil.which("claude")` returns the bare npm
        # shim path if both `claude` and `claude.cmd` exist on PATH
        # (the bare shim satisfies `shutil.which` because Windows'
        # `PATHEXT` lists `.CMD`/`.BAT`/`.EXE` and the kernel
        # `CreateProcessW` accepts a bare shim path). But that bare
        # shim is a Node.js script, NOT a PE binary, and
        # `subprocess.run` calling `CreateProcessW` on it returns
        # `WinError 193: %1 is not a valid Win32 application`.
        #
        # Fix: try the Windows-executable forms *first* (`.cmd`,
        # `.bat`, `.exe`), and only fall back to the bare name if
        # none of those resolve. Order matters: `.cmd` / `.bat` are
        # checked before `.exe` because most npm-published CLIs ship
        # a `.cmd` entry point and no `.exe`.
        #
        # If `name` already carries a suffix, that suffix is the first
        # candidate — `shutil.which("claude.cmd")` returns the right
        # path on the first try, and the loop degenerates to a no-op.
        candidates: list[str] = []
        for sfx in _WINDOWS_EXECUTABLE_SUFFIXES:
            if name.endswith(sfx):
                candidates.append(name)
                break
        else:
            # `name` had no recognized suffix. Add it last so the
            # suffixed forms get first pick.
            pass
        for sfx in _WINDOWS_EXECUTABLE_SUFFIXES:
            if not name.endswith(sfx):
                candidates.append(name + sfx)
        # Only fall back to the bare name if it does NOT have a
        # recognized suffix. If it does, the suffixed forms have
        # already been added above.
        has_suffix = any(name.endswith(sfx) for sfx in _WINDOWS_EXECUTABLE_SUFFIXES)
        if not has_suffix:
            candidates.append(name)
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                return found
        return None
    return shutil.which(name)


def to_json(data: object) -> str:
    """Serialise data as pretty JSON."""
    return json.dumps(data, indent=2, sort_keys=True)
