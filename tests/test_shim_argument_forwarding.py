"""Regression test for the PowerShell shim argument-forwarding fix.

Run with `python -m pytest tests/test_shim_argument_forwarding.py -v`.
If pytest is not installed: `pip install -r requirements-dev.txt`.

The Windows PowerShell shims (`scripts/powershell/agent-*.ps1`) used to
declare their own `[CmdletBinding()] param()` block with named
parameters (`$Repo`, `$Task`, …) and rebuild the argv list before
forwarding to `dispatch.py`. This produced two failure modes:

1. PowerShell's strict param binding rejected unknown args (`--help`,
   `-h`, custom flags) with "A parameter cannot be found that matches
   parameter name" before python ever ran. Users could not see help.
2. Pre-declared defaults like `[string]$Task = "general"` were always
   truthy, so the shim's `$forward += @('--task', $Task)` always added
   `--task general` even when the user passed nothing. Drift between
   the shim's hand-rolled flag list and the inner python module's
   argparse could (and did) produce the bug class where a shim injects
   `--repo` with no value before the user's args reach the inner
   parser, yielding the "argument --repo: expected one argument" error.

The fix is to make every shim a thin pass-through: a single
`[Parameter(ValueFromRemainingArguments=$true)] [string[]]$Rest`
captures every arg, including `--help`, and forwards it verbatim to
`dispatch.py <verb> @Rest`. The inner python module's argparse is the
single source of truth for argument parsing.

This test exercises the `dispatch.py -> command.main()` chain that the
shim now invokes. It uses `subprocess.run` to launch the actual
dispatch.py script and verifies:

- The user's reported commands run without "argument --repo: expected
  one argument" (i.e. no injected empty `--repo`).
- `--help` is consumed by the inner argparse (returns exit code 0; the
  shim's old `param()` block would have made python never see it).
- `--task code`, `--repo .`, `--repo <abs path>`, and `--print-cmd`
  all reach the inner module cleanly.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_PYTHON_SRC = _REPO_ROOT / "scripts" / "python"
_DISPATCH = _PYTHON_SRC / "dispatch.py"


def _python() -> str:
    """Return the python interpreter pytest is using."""
    return sys.executable


def _run_dispatch(argv: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Run `dispatch.py <argv>` and capture stdout/stderr/returncode.

    Mirrors exactly what the PowerShell shim now does: prepend the verb
    and forward the rest. Returns the completed process so tests can
    assert on the return code and the captured output.
    """
    cmd = [_python(), str(_DISPATCH), *argv]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        # Run from the repo root so the dispatcher's `find_repo_root()`
        # calls inside the inner modules don't wander off into /tmp.
        cwd=str(_REPO_ROOT),
    )


class TestShimArgumentForwarding:
    """The shim's pass-through contract: dispatch.py + inner argparse
    accept the user's args without injecting empty flags."""

    def test_help_passes_through_to_inner_argparse(self) -> None:
        """`dispatch.py <verb> --help` must reach the inner argparse and
        print help. Old shims with `[CmdletBinding()]` strict param
        binding rejected --help at the PowerShell layer; the user saw
        "parameter not found" instead of help text.
        """
        for verb in ("scan", "go", "check", "init", "bootstrap", "review", "test", "claude", "fleet", "overnight"):
            result = _run_dispatch([verb, "--help"])
            # argparse's --help exits 0 after printing to stdout.
            assert result.returncode == 0, (
                f"dispatch.py {verb} --help should exit 0; got {result.returncode}\n"
                f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
            )
            # The inner module's argparse prints a usage line to stdout.
            assert "usage:" in result.stdout, (
                f"dispatch.py {verb} --help should print usage to stdout; got:\n{result.stdout[:500]}"
            )
            # Critical: no "expected one argument" error from an injected
            # empty --repo (the bug class this test exists to prevent).
            assert "expected one argument" not in result.stderr, (
                f"dispatch.py {verb} --help should not have an empty-arg error in stderr; got:\n{result.stderr[:500]}"
            )

    def test_task_code_runs_without_repo(self) -> None:
        """`dispatch.py go --task code` must run; --repo is optional.

        The user reported `agent-go --task code` failed with
        "argument --repo: expected one argument". After the fix, the
        shim does not pre-declare `--repo`, so the inner `agent_go.main`
        sees `--task code` and falls back to `find_repo_root()` for
        `--repo`.
        """
        result = _run_dispatch(["go", "--task", "code", "--no-bootstrap", "--print-cmd"])
        # --print-cmd exits 0 before launching the model.
        assert result.returncode == 0, (
            f"dispatch.py go --task code --no-bootstrap --print-cmd should exit 0; got {result.returncode}\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )
        # And it must not contain the "expected one argument" error.
        assert "expected one argument" not in result.stderr

    def test_repo_dot_runs(self) -> None:
        """`dispatch.py go --repo . --task code` must work."""
        result = _run_dispatch(["go", "--repo", ".", "--task", "code", "--no-bootstrap", "--print-cmd"])
        assert result.returncode == 0, (
            f"dispatch.py go --repo . --task code should exit 0; got {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )
        assert "expected one argument" not in result.stderr

    def test_repo_absolute_path_runs(self) -> None:
        """`dispatch.py go --repo C:\\...` must work.

        The user reported `agent-go --repo "C:\\Users\\...\\TeamTasksBoard"`
        failed with the empty-arg error. The fix is to never inject
        `--repo` from the shim.
        """
        # Use the workbench root as the absolute repo path — it's
        # always present and matches the cwd we pass to subprocess.
        repo_path = str(_REPO_ROOT)
        result = _run_dispatch(
            ["go", "--repo", repo_path, "--task", "code", "--no-bootstrap", "--print-cmd"]
        )
        assert result.returncode == 0, (
            f"dispatch.py go --repo <abs> --task code should exit 0; got {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )
        assert "expected one argument" not in result.stderr

    def test_print_cmd_does_not_require_repo(self) -> None:
        """`dispatch.py go --print-cmd` must run; --repo is irrelevant
        for this code path (the inner module exits before touching
        the repo). Old shims that always injected --repo would force
        the user to pass it for --print-cmd too. The fix removes that.
        """
        result = _run_dispatch(["go", "--print-cmd"])
        assert result.returncode == 0
        assert "expected one argument" not in result.stderr
        # --print-cmd should emit the install one-liner.
        assert "install.ps1" in result.stdout

    def test_scan_help_does_not_inject_empty_repo(self) -> None:
        """The most direct regression test: `agent-scan --help` must
        not produce the "argument --repo: expected one argument" error.
        Before the fix, the shim's pre-declared `[string]$Repo` (which
        PowerShell binds to '' when not passed) plus the
        `if ($Repo) { ... }` guard could, on some PowerShell versions,
        forward `--repo` with no value, producing this error in the
        inner `scan_repo.main()`.
        """
        result = _run_dispatch(["scan", "--help"])
        assert result.returncode == 0
        assert "expected one argument" not in result.stderr
        # And the inner scan_repo's help text is present.
        assert "Scan a repository" in result.stdout

    def test_review_defaults_to_review_task(self) -> None:
        """`agent-review` (no args) must default to --task review and
        --show-files (matches the legacy `agent-review` shim that used
        to inject those by hand). The fix moved the defaults from the
        shim into `build_prompt.py` so the behavior is preserved
        without any shim-side flag injection.
        """
        result = _run_dispatch(["review", "--output", str(_REPO_ROOT / ".agent" / "_test_review_default.md")])
        # The output path's parent must exist for this to succeed; the
        # inner module creates it. We just want a clean exit.
        assert result.returncode == 0, (
            f"dispatch.py review should exit 0; got {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )
        # And the loaded-files report is on by default.
        assert "loaded" in result.stderr

    @pytest.mark.parametrize(
        "verb,args",
        [
            ("init", ["--help"]),
            ("scan", ["--help"]),
            ("check", ["--help"]),
            ("review", ["--help"]),
            ("test", ["--help"]),
            ("claude", ["--help"]),
            ("bootstrap", ["--help"]),
            ("fleet", ["--help"]),
            ("overnight", ["--help"]),
            ("go", ["--help"]),
        ],
    )
    def test_each_verb_help_works(self, verb: str, args: list[str]) -> None:
        """Every verb's --help must reach the inner argparse.

        Parametrized so a regression in any single shim shows up as a
        single named failure with the verb in the test id.
        """
        result = _run_dispatch([verb, *args])
        assert result.returncode == 0
        assert "expected one argument" not in result.stderr
        assert "usage:" in result.stdout
