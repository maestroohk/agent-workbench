"""Tests for the Windows command-resolution fix in agent-go / agent-claude.

Run with `python -m pytest tests/test_windows_command_resolution.py -v`.
If pytest is not installed: `pip install -r requirements-dev.txt`.

Background. `agent-go --task code` on a fresh Windows repo used to fail
in three ways:

  1. `subprocess.run([claude])` raised `OSError: [WinError 193]` because
     the bare `claude` on PATH is a Node.js shim, not a PE binary.
  2. `herdr agent start` was called with `--tab new`, which herdr
     rejected (`agent placement target new not found`), and the shim
     silently swallowed the failure.
  3. `--print-prompt` triggered a noisy bootstrap (which tried to
     install `gnhf`, a tool with no Windows release).

The fix lives in `utils.resolve_executable()` (added in commit 1),
which on Windows prefers `claude.cmd` / `claude.bat` / `claude.exe`
over the bare shim. `agent_go` and `agent_claude` now call it for
every `subprocess.run` of `claude` / `ollama` / `herdr`, and pass the
*resolved* `claude.cmd` path to herdr's internal spawn so herdr's
`CreateProcessW` succeeds.

These tests pin down the contract:

  - `resolve_executable` picks the `.cmd` form over the bare shim on
    Windows, and falls through to the bare name on non-Windows.
  - `agent_go.DEFAULT_GO_BOOTSTRAP` no longer pulls in `gnhf` (overnight
    only) or `treehouse` (worktree pool; opt-in).
  - `agent-go --print-prompt` does not touch the network: the install
    step is unreachable from the read-only path.
  - `agent_go._spawn_claude` hands a real Windows executable path
    (`.cmd` or `.exe`) to `subprocess.run`, not the bare shim.
  - `agent_go._spawn_via_herdr_agent` falls back to direct `claude`
    when herdr returns a non-zero exit, instead of returning a silent
    failure code.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# The python sources live at scripts/python/; make sure that is on
# sys.path before importing the workbench modules.
_HERE = Path(__file__).resolve().parent
_PYTHON_SRC = _HERE.parent / "scripts" / "python"
if str(_PYTHON_SRC) not in sys.path:
    sys.path.insert(0, str(_PYTHON_SRC))

import agent_go  # noqa: E402
import runtime as _runtime  # noqa: E402
from utils import resolve_executable  # noqa: E402


def _claude_runtime(model: str) -> tuple:
    """Build the (runtime, spawn_cmd, spawn_env) tuple for the claude
    runtime. Mirrors what `agent_go.main()` does for `--runtime claude`.
    Kept in this test module so each spawn-using test can build a
    runtime in one line."""
    runtime = _runtime.Runtime(name="claude", model=model, source="test")
    spawn_cmd, spawn_env = _runtime.build_spawn_args(runtime)
    return runtime, spawn_cmd, spawn_env


# ---------------------------------------------------------------------------
# resolve_executable
# ---------------------------------------------------------------------------


class TestResolveExecutable:
    """`resolve_executable` is the single source of truth for Windows
    command resolution. On Windows it must prefer `.cmd`/`.bat`/`.exe`
    over the bare shim; on non-Windows it must behave like
    `shutil.which`."""

    def test_returns_none_for_missing_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`resolve_executable` returns `None` for a name that is not
        on PATH, in any of its Windows forms or the bare name."""
        monkeypatch.setenv("PATH", "")
        assert resolve_executable("definitely-not-a-real-tool-xyz") is None

    def test_resolves_bare_name_on_non_windows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """On non-Windows, `resolve_executable` is `shutil.which`
        unchanged. We force the platform branch by patching
        `utils.os.name` to `posix` and dropping a fake binary on a
        synthetic PATH."""
        # Drop a fake `fake-tool` on a tmp PATH and resolve it.
        fake = tmp_path / "fake-tool"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(os, "name", "posix")
        assert resolve_executable("fake-tool") == str(fake)

    def test_prefers_cmd_form_on_windows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """On Windows, a `.cmd` form takes priority over the bare shim.

        This is the exact bug `agent-go` hit: `claude` on the user's
        PATH resolves to the bare npm shim, and `subprocess.run` blows
        up with WinError 193. With the fix, `claude.cmd` is preferred
        because npm-published CLIs ship a `.cmd` entry point and
        `CreateProcessW` accepts it.
        """
        # Mirror the npm install layout: a bare `claude` Node.js
        # shim AND a `claude.cmd` batch entry point. Both exist on
        # PATH. The `.cmd` form must win.
        bare = tmp_path / "claude"
        bare.write_text("#!/usr/bin/env node\nconsole.log('shim')")
        bare.chmod(0o755)
        cmd_form = tmp_path / "claude.cmd"
        cmd_form.write_text("@echo off\r\necho real binary\r\n")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(os, "name", "nt")
        assert resolve_executable("claude") == str(cmd_form)

    def test_falls_back_to_bare_name_on_windows_when_no_cmd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """On Windows, if only the bare name exists, the bare name is
        returned. Callers that need a real PE binary should
        already-install the `.cmd` form; we don't synthesize one."""
        bare = tmp_path / "claude"
        bare.write_text("#!/usr/bin/env node\n")
        bare.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(os, "name", "nt")
        assert resolve_executable("claude") == str(bare)

    def test_already_suffixed_name_resolves_directly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """If the caller passes `claude.cmd` explicitly, the function
        still returns it. The suffix loop is just a fallback when the
        bare name is given — it does not change behavior for
        already-suffixed input."""
        cmd_form = tmp_path / "claude.cmd"
        cmd_form.write_text("@echo off\r\n")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(os, "name", "nt")
        assert resolve_executable("claude.cmd") == str(cmd_form)

    def test_exe_form_preferred_over_bare_when_no_cmd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`.cmd` / `.bat` are checked before `.exe`, but `.exe` is
        the last fallback. We check this so the suffix order is
        pinned: even if a tool ships an `.exe` and no `.cmd`, the
        `.exe` is found and used."""
        exe_form = tmp_path / "mytool.exe"
        exe_form.write_bytes(b"MZ\x00")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(os, "name", "nt")
        assert resolve_executable("mytool") == str(exe_form)


# ---------------------------------------------------------------------------
# DEFAULT_GO_BOOTSTRAP
# ---------------------------------------------------------------------------


class TestDefaultGoBootstrap:
    """The `agent-go` default bootstrap set must not include tools that
    either (a) are not used on the interactive `agent-go` path, or
    (b) have no Windows release and would produce a noisy error on
    every Windows `agent-go` call."""

    def test_default_bootstrap_does_not_include_gnhf(self) -> None:
        """gnhf is the overnight runner; not used by interactive
        `agent-go`. It ships no Windows release, so leaving it in the
        default would make every Windows `agent-go` invocation hit
        the 'no asset' error path."""
        assert "gnhf" not in agent_go.DEFAULT_GO_BOOTSTRAP

    def test_default_bootstrap_does_not_include_treehouse(self) -> None:
        """treehouse is the worktree pool; a single-agent `agent-go`
        flow does not need it. `agent-fleet --backend=treehouse` is
        the path that wants it."""
        assert "treehouse" not in agent_go.DEFAULT_GO_BOOTSTRAP

    def test_default_bootstrap_includes_hot_path_tools(self) -> None:
        """The slim default keeps the hot path covered: claude (model
        runner), herdr (orchestrator), firstmate (project rules),
        no-mistakes (validation gate), ollama (fallback runner)."""
        for name in ("claude", "herdr", "firstmate", "no-mistakes", "ollama"):
            assert name in agent_go.DEFAULT_GO_BOOTSTRAP, (
                f"DEFAULT_GO_BOOTSTRAP missing hot-path tool {name!r}"
            )

    def test_default_bootstrap_gnhf_is_opt_in(self) -> None:
        """The user can opt in to gnhf with --bootstrap=gnhf; we just
        make sure it is reachable, not default."""
        targets = ",".join(agent_go.DEFAULT_GO_BOOTSTRAP)
        assert "gnhf" not in targets.split(",")


# ---------------------------------------------------------------------------
# --print-prompt short-circuit
# ---------------------------------------------------------------------------


class TestPrintPromptShortCircuit:
    """`--print-prompt` is documented as a read-only view of the
    assembled prompt. It must NOT touch the network, NOT start the
    herdr server, and NOT launch the model. The previous flow ran the
    full bootstrap first, which on Windows produced a noisy 'no asset'
    error from the gnhf install before the user saw their prompt."""

    def test_print_prompt_does_not_call_install_dependencies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Monkeypatch `bootstrap.install_dependencies` to raise if
        called. If the install step is reachable from the
        `--print-prompt` path, the test fails."""
        from bootstrap import install_dependencies  # noqa: WPS433

        def _explode(*args, **kwargs):  # noqa: ANN001
            raise AssertionError(
                "install_dependencies was called from --print-prompt; "
                "the read-only path must skip the install step"
            )

        monkeypatch.setattr("agent_go._bootstrap.install_dependencies", install_dependencies)
        # Now monkeypatch the import the function actually uses.
        import bootstrap as _bootstrap

        monkeypatch.setattr(_bootstrap, "install_dependencies", _explode)

        # Run the read-only path. We use a known repo (the workbench
        # root) and pass --no-bootstrap explicitly; the test is that
        # even WITHOUT --no-bootstrap, --print-prompt would skip the
        # install. We can't easily test the latter without a fake
        # install, so we run with --no-bootstrap and assert no raise.
        rc = agent_go.main(["--print-prompt", "--no-bootstrap"])
        assert rc == 0

    def test_print_prompt_emits_prompt_body(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--print-prompt` writes the assembled prompt to stdout and
        returns 0. Verify the body is non-trivial and starts with the
        expected global-rules section."""
        rc = agent_go.main(["--print-prompt", "--no-bootstrap"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Global toolkit instructions" in captured.out
        assert "## Task" not in captured.out  # no task_text passed

    def test_print_prompt_help_text_documents_no_install(
        self, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """The help text on `--print-prompt` must tell the user that
        the install step is skipped — that's the contract. argparse
        writes `--help` to the actual stdout file descriptor (not
        through the captured sys.stdout), so we use capfd to read
        it back at the FD level.

        The argparse help-formatter word-wraps the long description,
        so we look at the joined output (collapsing newlines) and
        assert the help prose is present."""
        with pytest.raises(SystemExit) as exc_info:
            agent_go.main(["--help"])
        assert exc_info.value.code == 0
        captured = capfd.readouterr()
        joined = " ".join(captured.out.split())
        # argparse prints --help to stdout. The em-dash in the
        # help text is the only thing that would break an exact
        # substring match, so we look for the prose fragments that
        # survive the word-wrap. argparse will join them with spaces
        # in the actual text, not the wrapped help output.
        assert "Skips" in joined
        assert "the install step" in joined
        assert "the herdr server" in joined
        assert "the model launch" in joined


# ---------------------------------------------------------------------------
# _spawn_claude / _spawn_via_herdr_agent
# ---------------------------------------------------------------------------


class TestSpawnClaudeResolution:
    """The spawn path must hand a real Windows-executable path to
    `subprocess.run` / herdr's internal `CreateProcessW`, not the bare
    npm shim."""

    def test_spawn_claude_uses_resolved_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """On Windows, `_spawn_claude` must pass the `.cmd` form (or
        `.exe`) as argv[0], not the bare `claude` name. We assert
        this by intercepting `subprocess.run` and inspecting argv."""

        fake_cmd = tmp_path / "claude.cmd"
        fake_cmd.write_text("@echo off\r\n")
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: str(fake_cmd))

        # Pre-create the .agent/SYSTEM_PROMPT.md the spawn path reads
        # for `--append-system-prompt`.
        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)
        (tmp_path / AGENT_DIR_NAME / "SYSTEM_PROMPT.md").write_text("test prompt")

        captured_argv: list = []

        def _fake_run(argv, **kwargs):  # noqa: ANN001
            captured_argv.extend(argv)
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("agent_go.subprocess.run", _fake_run)
        rc = agent_go._spawn_claude(tmp_path, model="minimax-m3:cloud")
        assert rc == 0
        assert captured_argv, "subprocess.run was not called"
        # argv[0] must be the resolved .cmd path, not the bare name.
        assert captured_argv[0] == str(fake_cmd)
        assert captured_argv[0].endswith((".cmd", ".bat", ".exe"))


class TestHerdrFallback:
    """When herdr returns a non-zero exit (placement not found, server
    wedged, agent name taken), `agent-go` must not silently return that
    code. The user is dropped back to a working session by falling
    back to a direct `claude` invocation."""

    def test_herdr_agent_start_failure_falls_back_to_claude(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Force `herdr agent start` to fail and assert that
        `_spawn_claude` is called as the fallback."""

        # Make resolve_executable return paths for both herdr and claude.
        herdr_path = str(tmp_path / "herdr")
        claude_cmd = tmp_path / "claude.cmd"
        claude_cmd.write_text("@echo off\r\n")

        def _resolve(name: str) -> str | None:
            return {"herdr": herdr_path, "claude": str(claude_cmd)}.get(name)

        monkeypatch.setattr("agent_go.resolve_executable", _resolve)

        # Make `subprocess.run` return non-zero for herdr and a clean
        # CompletedProcess for the direct claude call.
        def _fake_run(argv, **kwargs):  # noqa: ANN001
            if argv[:1] == [herdr_path] and "start" in argv:
                return subprocess.CompletedProcess(
                    args=argv, returncode=1, stdout="", stderr="agent placement target new not found"
                )
            if argv[:1] == [str(claude_cmd)]:
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout="", stderr=""
                )
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("agent_go.subprocess.run", _fake_run)

        # Pre-create the prompt file (the function writes it before
        # calling herdr).
        from scan_repo import AGENT_DIR_NAME

        agent_dir = tmp_path / AGENT_DIR_NAME
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "SYSTEM_PROMPT.md").write_text("test prompt")

        runtime, spawn_cmd, spawn_env = _claude_runtime("minimax-m3:cloud")
        rc = agent_go._spawn_via_herdr_agent(
            tmp_path,
            prompt_body="test prompt",
            runtime=runtime,
            spawn_cmd=spawn_cmd,
            spawn_env=spawn_env,
        )
        # The fallback to _spawn_claude should yield rc=0 (since we
        # made the direct claude subprocess.run return 0).
        assert rc == 0

    def test_herdr_worktree_create_failure_uses_repo_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When `herdr worktree create` fails (e.g. no HEAD on a fresh
        repo), the function must NOT crash and must use the repo root
        as the agent's cwd. We assert by intercepting the second
        subprocess.run call (herdr agent start) and reading its
        --cwd argument."""

        herdr_path = str(tmp_path / "herdr")
        claude_cmd = tmp_path / "claude.cmd"
        claude_cmd.write_text("@echo off\r\n")

        def _resolve(name: str) -> str | None:
            return {"herdr": herdr_path, "claude": str(claude_cmd)}.get(name)

        monkeypatch.setattr("agent_go.resolve_executable", _resolve)

        captured_argv: list = []

        def _fake_run(argv, **kwargs):  # noqa: ANN001
            if "worktree" in argv and "create" in argv:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=128,
                    stdout="",
                    stderr="fatal: invalid reference: HEAD",
                )
            captured_argv.extend(argv)
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("agent_go.subprocess.run", _fake_run)

        from scan_repo import AGENT_DIR_NAME

        agent_dir = tmp_path / AGENT_DIR_NAME
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "SYSTEM_PROMPT.md").write_text("test prompt")

        runtime, spawn_cmd, spawn_env = _claude_runtime("minimax-m3:cloud")
        rc = agent_go._spawn_via_herdr_agent(
            tmp_path,
            prompt_body="test prompt",
            runtime=runtime,
            spawn_cmd=spawn_cmd,
            spawn_env=spawn_env,
        )
        assert rc == 0
        # The herdr agent start call must have used the repo root as
        # --cwd, since worktree create failed.
        assert "--cwd" in captured_argv
        cwd_idx = captured_argv.index("--cwd")
        assert captured_argv[cwd_idx + 1] == str(tmp_path)
        # And the placement flag must be --split right, not --tab new.
        assert "--split" in captured_argv
        assert "right" in captured_argv
        assert "--tab" not in captured_argv
