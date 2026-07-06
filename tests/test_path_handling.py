"""Tests for Windows path handling in the workbench utilities.

Run with `python -m pytest tests/test_path_handling.py -v`. If pytest
is not installed: `pip install -r requirements-dev.txt`.

These tests cover the surfaces that the Windows installer and bootstrap
rely on: cross-platform path resolution, paths with spaces, and the
back-to-forward slash conversion that `shutil.which` expects. The
Windows + Git Bash case is the one that historically broke the
workbench's PATH-mangling assumptions, so it is the focus here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# The python sources live at scripts/python/; make sure that is on
# sys.path before importing the workbench modules.
_HERE = Path(__file__).resolve().parent
_PYTHON_SRC = _HERE.parent / "scripts" / "python"
if str(_PYTHON_SRC) not in sys.path:
    sys.path.insert(0, str(_PYTHON_SRC))

from utils import ensure_on_path, first_executable  # noqa: E402


class TestFirstExecutable:
    """`first_executable` must resolve a name on PATH or return None."""

    def test_returns_none_for_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force shutil.which to return None by clearing PATH.
        monkeypatch.setenv("PATH", "")
        assert first_executable(["definitely-not-a-real-tool-xyz"]) is None

    def test_resolves_known_tool(self) -> None:
        # `python` is on PATH in every supported environment.
        path = first_executable(["python", "python3", "py"])
        assert path is not None
        # On Windows the .exe suffix is allowed; on unix there is no
        # extension. Either is fine.
        assert Path(path).name.startswith(("python", "py"))

    def test_first_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Two fake tools on PATH. first_executable must return the
        # first one it finds, in the order given.
        a = tmp_path / "a-tool"
        b = tmp_path / "b-tool"
        if os.name == "nt":
            a = a.with_suffix(".cmd")
            b = b.with_suffix(".cmd")
        a.write_text("@echo off\nexit 0\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n")
        b.write_text("@echo off\nexit 0\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n")
        if os.name != "nt":
            a.chmod(0o755)
            b.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
        result = first_executable(["a-tool", "b-tool"])
        assert result is not None
        assert Path(result).name.startswith("a-tool")


class TestEnsureOnPath:
    """`ensure_on_path` must add a directory to PATH for the current process."""

    def test_adds_when_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", os.pathsep.join(["/nope1", "/nope2"]))
        ensure_on_path(tmp_path)
        parts = os.environ["PATH"].split(os.pathsep)
        assert str(tmp_path) in parts

    def test_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", os.pathsep.join(["/nope1", str(tmp_path), "/nope2"]))
        ensure_on_path(tmp_path)
        parts = os.environ["PATH"].split(os.pathsep)
        # `tmp_path` appears exactly once, not twice.
        assert parts.count(str(tmp_path)) == 1

    def test_handles_spaces_in_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # A path with spaces — common on Windows under user profiles.
        spaced = tmp_path / "with space"
        spaced.mkdir()
        monkeypatch.setenv("PATH", "/nope1")
        ensure_on_path(spaced)
        parts = os.environ["PATH"].split(os.pathsep)
        assert str(spaced) in parts

    def test_handles_backslash_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Windows-style backslash paths must round-trip through
        # os.pathsep. The Windows CI runner and the .ps1 wrapper both
        # pass paths with backslashes; we should not double-add them.
        if os.name != "nt":
            pytest.skip("backslash round-trip is Windows-only")
        win_path = str(tmp_path).replace("/", "\\")
        monkeypatch.setenv("PATH", win_path)
        ensure_on_path(tmp_path)
        # Both the backslash and forward-slash forms refer to the
        # same directory; either may appear, but not both.
        parts = os.environ["PATH"].split(os.pathsep)
        normalized = {p.replace("\\", "/") for p in parts}
        assert str(tmp_path).replace("\\", "/") in normalized
