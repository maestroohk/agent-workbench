"""Tests for the herdr JSON parsing + auto-attach behaviour in agent-go.

Run with `python -m pytest tests/test_herdr_json_parsing.py -v`.

Background. `agent-go --task code` on a fresh Windows repo used to
silently spawn the agent in the user's home directory, because the
worktree-create JSON envelope was passed verbatim as `--cwd` to
`herdr agent start`. The user was also dropped at the PowerShell
prompt with no clear "what to do next" after a successful run.

The fix:

  1. `utils.parse_json_loose()` extracts a JSON object from a string
     that may have leading non-JSON noise (herdr's `--json` envelopes
     are sometimes preceded by a status line).
  2. `agent_go._extract_worktree_path` reads the worktree path out of
     the `worktree_created` envelope.
  3. `agent_go._extract_agent_info` reads the agent's actual cwd out
     of the `agent_started` envelope and warns if it differs from
     what was requested.
  4. After a successful spawn, an instruction block is printed with
     the agent name, worktree path, actual cwd, and the manual
     `herdr agent attach <name>` command.
  5. If stdout is a TTY and `AGENT_GO_NO_AUTO_ATTACH` is not set,
     `agent-go` runs `herdr agent attach primary` as a blocking
     foreground call so the user lands directly in the agent's pane.
  6. `--no-attach` on the CLI (or `AGENT_GO_NO_AUTO_ATTACH=1`) skips
     the auto-attach and just prints the instruction block.

These tests pin down the contract end-to-end: a fake `subprocess.run`
returns herdr's real JSON envelope shape, and we assert that the
resulting `herdr agent start` call receives the worktree path as
`--cwd`, the instruction block contains the right info, and the
auto-attach behaviour respects the env var and CLI flag.
"""
from __future__ import annotations

import json
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
from utils import parse_json_loose  # noqa: E402


# ---------------------------------------------------------------------------
# parse_json_loose
# ---------------------------------------------------------------------------


class TestParseJsonLoose:
    """`parse_json_loose` is the single source of truth for parsing
    herdr's JSON envelopes. It must handle the clean case, the
    leading-noise case, multi-line pretty-printed JSON, and the
    no-JSON case."""

    def test_clean_object(self) -> None:
        assert parse_json_loose('{"a": 1, "b": 2}') == {"a": 1, "b": 2}

    def test_leading_non_json_noise(self) -> None:
        # herdr sometimes prints a status line before the JSON.
        text = "herdr: creating worktree...\n" + json.dumps({"worktree_created": {"worktree": {"path": "C:\\foo"}}})
        assert parse_json_loose(text) == {"worktree_created": {"worktree": {"path": "C:\\foo"}}}

    def test_multiline_pretty_printed(self) -> None:
        text = json.dumps({"worktree_created": {"worktree": {"path": "C:\\foo", "label": "agent-go"}}}, indent=2)
        loaded = parse_json_loose(text)
        assert loaded is not None
        assert loaded["worktree_created"]["worktree"]["path"] == "C:\\foo"

    def test_returns_none_for_empty_string(self) -> None:
        assert parse_json_loose("") is None

    def test_returns_none_for_whitespace(self) -> None:
        assert parse_json_loose("   \n\t  ") is None

    def test_returns_none_for_plain_text(self) -> None:
        assert parse_json_loose("not json at all") is None

    def test_returns_none_for_non_dict_json(self) -> None:
        # An array, number, or string is not what we expect from herdr.
        assert parse_json_loose("[1, 2, 3]") is None
        assert parse_json_loose("42") is None
        assert parse_json_loose('"hello"') is None

    def test_trailing_garbage_after_object(self) -> None:
        # Tolerates trailing lines after the closing brace.
        text = json.dumps({"path": "C:\\foo"}) + "\nherdr: done"
        assert parse_json_loose(text) == {"path": "C:\\foo"}

    def test_windows_path_with_spaces_and_backslashes(self) -> None:
        # The exact path shape that was failing in the user's bug report.
        path = "C:\\Users\\Test User\\repos\\My App\\worktree-brave-river-57c0"
        text = json.dumps({"worktree_created": {"worktree": {"path": path}}})
        loaded = parse_json_loose(text)
        assert loaded is not None
        assert loaded["worktree_created"]["worktree"]["path"] == path


# ---------------------------------------------------------------------------
# _extract_worktree_path
# ---------------------------------------------------------------------------


class TestExtractWorktreePath:
    """`_extract_worktree_path` returns the path string from a
    `worktree_created` envelope, or None. Tolerant of two shapes."""

    def test_envelope_shape(self) -> None:
        payload = {"worktree_created": {"worktree": {"path": "C:\\foo\\worktree-x"}}}
        assert agent_go._extract_worktree_path(payload) == "C:\\foo\\worktree-x"

    def test_top_level_path_shape(self) -> None:
        # Future-proof: if herdr changes the envelope, a top-level
        # `path` key should still work.
        assert agent_go._extract_worktree_path({"path": "C:\\foo"}) == "C:\\foo"

    def test_none_input(self) -> None:
        assert agent_go._extract_worktree_path(None) is None

    def test_empty_input(self) -> None:
        assert agent_go._extract_worktree_path({}) is None

    def test_wrong_inner_types(self) -> None:
        # If `worktree_created` is not a dict, fall through to top-level.
        assert agent_go._extract_worktree_path({"worktree_created": "oops"}) is None
        # If `worktree` is a string (not a dict), return None.
        assert agent_go._extract_worktree_path({"worktree_created": {"worktree": "oops"}}) is None


# ---------------------------------------------------------------------------
# _extract_agent_info
# ---------------------------------------------------------------------------


class TestExtractAgentInfo:
    """`_extract_agent_info` returns (cwd, agent_name) from an
    `agent_started` envelope, or (None, None)."""

    def test_envelope_shape(self) -> None:
        payload = {
            "agent_started": {
                "agent": "primary",
                "cwd": "C:\\foo\\worktree-x",
                "argv": ["claude", "--append-system-prompt", "..."],
            }
        }
        assert agent_go._extract_agent_info(payload) == ("C:\\foo\\worktree-x", "primary")

    def test_top_level_shape(self) -> None:
        assert agent_go._extract_agent_info({"agent": "primary", "cwd": "C:\\foo"}) == ("C:\\foo", "primary")

    def test_none_input(self) -> None:
        assert agent_go._extract_agent_info(None) == (None, None)

    def test_missing_cwd(self) -> None:
        assert agent_go._extract_agent_info({"agent_started": {"agent": "primary"}}) == (None, "primary")

    def test_missing_name(self) -> None:
        assert agent_go._extract_agent_info({"agent_started": {"cwd": "C:\\foo"}}) == ("C:\\foo", None)

    def test_name_alias(self) -> None:
        # Some envelopes may use `name` instead of `agent`.
        assert agent_go._extract_agent_info({"agent_started": {"name": "primary", "cwd": "C:\\foo"}}) == ("C:\\foo", "primary")


# ---------------------------------------------------------------------------
# _paths_differ
# ---------------------------------------------------------------------------


class TestPathsDiffer:
    """`_paths_differ` is True for paths that are not the same after
    case + separator normalisation."""

    def test_same_path(self, tmp_path: Path) -> None:
        assert agent_go._paths_differ(str(tmp_path), str(tmp_path)) is False

    def test_different_paths(self) -> None:
        assert agent_go._paths_differ("C:\\foo", "C:\\bar") is True

    def test_empty_strings(self) -> None:
        # Empty / None inputs are treated as "no info", not as differing.
        assert agent_go._paths_differ("", "C:\\foo") is False
        assert agent_go._paths_differ("C:\\foo", "") is False
        assert agent_go._paths_differ("", "") is False

    def test_windows_backslashes_vs_forward_slashes(self) -> None:
        # On Windows, os.path.normpath treats both as separators; on
        # POSIX the assertion holds by case.
        if os.name == "nt":
            assert agent_go._paths_differ("C:\\foo\\bar", "C:/foo/bar") is False

    def test_case_insensitive_on_windows(self) -> None:
        if os.name == "nt":
            assert agent_go._paths_differ("C:\\Foo\\Bar", "c:\\foo\\bar") is False


# ---------------------------------------------------------------------------
# End-to-end: _spawn_via_herdr_agent uses parsed worktree path
# ---------------------------------------------------------------------------


def _make_fake_run(worktree_json: str, agent_started_json: str, captured: list):
    """Return a fake `subprocess.run` that returns herdr's JSON envelopes."""

    def _fake_run(argv, **kwargs):  # noqa: ANN001
        captured.append(list(argv))
        if "worktree" in argv and "create" in argv:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=worktree_json, stderr="")
        if "agent" in argv and "start" in argv:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=agent_started_json, stderr="")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    return _fake_run


def _make_fake_resolve(tmp_path: Path):
    herdr_path = str(tmp_path / "herdr")
    claude_cmd = tmp_path / "claude.cmd"
    claude_cmd.write_text("@echo off\r\n")
    return {"herdr": herdr_path, "claude": str(claude_cmd)}


class TestSpawnHerdrAgentUsesWorktreePath:
    """The bug: `agent-go` passed the entire `worktree_created` JSON
    envelope as `--cwd` to `herdr agent start`. herdr silently fell
    back to the user's home directory, and the agent landed in $HOME.
    The fix: parse the JSON, extract the path, pass the path."""

    def test_worktree_path_extracted_from_json_envelope(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        herdr_path = _make_fake_resolve(tmp_path)["herdr"]
        paths = _make_fake_resolve(tmp_path)

        def _resolve(name: str):
            return paths.get(name)

        monkeypatch.setattr("agent_go.resolve_executable", _resolve)

        expected_path = r"C:\Users\henry\.herdr\worktrees\TeamTasksBoard\worktree-brave-river-57c0"
        worktree_json = json.dumps({
            "worktree_created": {
                "worktree": {"path": expected_path, "label": "agent-go"},
            }
        })
        agent_started_json = json.dumps({
            "agent_started": {
                "agent": "primary",
                "cwd": expected_path,
                "argv": ["claude.cmd", "--append-system-prompt", "..."],
            }
        })
        captured: list = []
        monkeypatch.setattr("agent_go.subprocess.run", _make_fake_run(worktree_json, agent_started_json, captured))

        # Disable auto-attach (the test is not a TTY and we want to
        # verify the instruction block separately).
        monkeypatch.setattr("agent_go._should_auto_attach", lambda: False)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)

        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)

        rc = agent_go._spawn_via_herdr_agent(
            tmp_path, prompt_body="test prompt", model="minimax-m3:cloud"
        )
        assert rc == 0

        # Find the `herdr agent start` call.
        start_calls = [c for c in captured if "agent" in c and "start" in c]
        assert len(start_calls) == 1
        start_argv = start_calls[0]
        # The cwd passed to herdr agent start must be the worktree path
        # extracted from the JSON envelope, not the raw JSON and not $HOME.
        cwd_idx = start_argv.index("--cwd")
        actual_cwd = start_argv[cwd_idx + 1]
        assert actual_cwd == expected_path
        assert not actual_cwd.startswith("{")

    def test_windows_path_with_spaces_round_trips(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A Windows path with spaces and backslashes must round-trip
        through parse_json_loose + _extract_worktree_path intact."""
        paths = _make_fake_resolve(tmp_path)
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: paths.get(name))

        expected_path = r"C:\Users\Test User\repos\My App\worktree-x"
        worktree_json = json.dumps({
            "worktree_created": {"worktree": {"path": expected_path}}
        })
        agent_started_json = json.dumps({
            "agent_started": {"agent": "primary", "cwd": expected_path}
        })
        captured: list = []
        monkeypatch.setattr("agent_go.subprocess.run", _make_fake_run(worktree_json, agent_started_json, captured))
        monkeypatch.setattr("agent_go._should_auto_attach", lambda: False)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)

        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)

        agent_go._spawn_via_herdr_agent(
            tmp_path, prompt_body="test prompt", model="minimax-m3:cloud"
        )
        start_calls = [c for c in captured if "agent" in c and "start" in c]
        start_argv = start_calls[0]
        cwd_idx = start_argv.index("--cwd")
        assert start_argv[cwd_idx + 1] == expected_path

    def test_top_level_path_shape_also_works(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """If herdr ever changes the envelope to a flat `{"path":"..."}`,
        we still extract the path correctly."""
        paths = _make_fake_resolve(tmp_path)
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: paths.get(name))

        expected_path = r"C:\foo\worktree-y"
        worktree_json = json.dumps({"path": expected_path})
        agent_started_json = json.dumps({"agent_started": {"agent": "primary", "cwd": expected_path}})
        captured: list = []
        monkeypatch.setattr("agent_go.subprocess.run", _make_fake_run(worktree_json, agent_started_json, captured))
        monkeypatch.setattr("agent_go._should_auto_attach", lambda: False)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)

        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)

        agent_go._spawn_via_herdr_agent(
            tmp_path, prompt_body="test prompt", model="minimax-m3:cloud"
        )
        start_calls = [c for c in captured if "agent" in c and "start" in c]
        cwd_idx = start_calls[0].index("--cwd")
        assert start_calls[0][cwd_idx + 1] == expected_path


# ---------------------------------------------------------------------------
# cwd mismatch warning
# ---------------------------------------------------------------------------


class TestCwdMismatchWarning:
    """If herdr reports an `agent_started.cwd` that differs from the
    worktree path we asked for, we must print a warn line and not
    silently claim success."""

    def test_mismatch_warns(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        paths = _make_fake_resolve(tmp_path)
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: paths.get(name))

        requested = r"C:\foo\worktree-correct"
        actual = r"C:\Users\henry"  # The original bug.
        worktree_json = json.dumps({"worktree_created": {"worktree": {"path": requested}}})
        agent_started_json = json.dumps({"agent_started": {"agent": "primary", "cwd": actual}})
        captured: list = []
        monkeypatch.setattr("agent_go.subprocess.run", _make_fake_run(worktree_json, agent_started_json, captured))
        monkeypatch.setattr("agent_go._should_auto_attach", lambda: False)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)

        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)

        rc = agent_go._spawn_via_herdr_agent(
            tmp_path, prompt_body="test prompt", model="minimax-m3:cloud"
        )
        assert rc == 0  # We do not crash on mismatch; we warn.
        out = capsys.readouterr().err
        assert "wrong directory" in out.lower() or actual in out
        assert actual in out  # The actual bad cwd appears in the warning.


# ---------------------------------------------------------------------------
# Instruction block + auto-attach
# ---------------------------------------------------------------------------


class TestInstructionBlock:
    """After a successful spawn, `agent-go` prints an instruction block
    with the agent name, the actual cwd, the worktree path, and the
    manual attach command. The user's `herdr agent attach primary`
    command must be in the output."""

    def test_instruction_block_includes_attach_command(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        paths = _make_fake_resolve(tmp_path)
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: paths.get(name))

        path = r"C:\foo\worktree-x"
        worktree_json = json.dumps({"worktree_created": {"worktree": {"path": path}}})
        agent_started_json = json.dumps({"agent_started": {"agent": "primary", "cwd": path}})
        captured: list = []
        monkeypatch.setattr("agent_go.subprocess.run", _make_fake_run(worktree_json, agent_started_json, captured))
        monkeypatch.setattr("agent_go._should_auto_attach", lambda: False)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)

        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)

        agent_go._spawn_via_herdr_agent(
            tmp_path, prompt_body="test prompt", model="minimax-m3:cloud"
        )
        out = capsys.readouterr().err
        # All four required lines are in the instruction block.
        assert "repo root" in out
        assert "worktree" in out
        assert "agent cwd" in out
        assert "agent name" in out
        assert "herdr agent attach primary" in out
        assert "NEXT STEP" in out
        # The actual paths appear.
        assert str(tmp_path) in out
        assert path in out

    def test_no_attach_flag_disables_auto_attach(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`--no-attach` must skip the auto-attach call. Verified by
        checking that `subprocess.run` is never called with an `attach`
        verb."""
        paths = _make_fake_resolve(tmp_path)
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: paths.get(name))

        path = r"C:\foo\worktree-x"
        worktree_json = json.dumps({"worktree_created": {"worktree": {"path": path}}})
        agent_started_json = json.dumps({"agent_started": {"agent": "primary", "cwd": path}})
        captured: list = []
        monkeypatch.setattr("agent_go.subprocess.run", _make_fake_run(worktree_json, agent_started_json, captured))
        # Even though we're "on a TTY", --no-attach must win.
        monkeypatch.setattr("agent_go._should_auto_attach", lambda: True)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)

        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)

        agent_go._spawn_via_herdr_agent(
            tmp_path, prompt_body="test prompt", model="minimax-m3:cloud", auto_attach=False
        )
        # No `herdr agent attach ...` call was made.
        attach_calls = [c for c in captured if "attach" in c]
        assert attach_calls == []

    def test_env_var_disables_auto_attach(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`AGENT_GO_NO_AUTO_ATTACH=1` must skip the auto-attach call.

        We mock `sys.stdout.isatty` to True (so the TTY check passes)
        and the env var to disable. The real `_should_auto_attach`
        must then return False and the auto-attach call must be skipped.
        """
        paths = _make_fake_resolve(tmp_path)
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: paths.get(name))

        path = r"C:\foo\worktree-x"
        worktree_json = json.dumps({"worktree_created": {"worktree": {"path": path}}})
        agent_started_json = json.dumps({"agent_started": {"agent": "primary", "cwd": path}})
        captured: list = []
        monkeypatch.setattr("agent_go.subprocess.run", _make_fake_run(worktree_json, agent_started_json, captured))
        # TTY check passes; only the env var should disable.
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setenv("AGENT_GO_NO_AUTO_ATTACH", "1")

        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)

        try:
            agent_go._spawn_via_herdr_agent(
                tmp_path, prompt_body="test prompt", model="minimax-m3:cloud"
            )
            attach_calls = [c for c in captured if "attach" in c]
            assert attach_calls == []
        finally:
            monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)

    def test_no_tty_disables_auto_attach(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When stdout is not a TTY (e.g. CI), auto-attach is skipped
        even when --no-attach is not passed."""
        paths = _make_fake_resolve(tmp_path)
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: paths.get(name))

        path = r"C:\foo\worktree-x"
        worktree_json = json.dumps({"worktree_created": {"worktree": {"path": path}}})
        agent_started_json = json.dumps({"agent_started": {"agent": "primary", "cwd": path}})
        captured: list = []
        monkeypatch.setattr("agent_go.subprocess.run", _make_fake_run(worktree_json, agent_started_json, captured))
        # Real _should_auto_attach with isatty=False.
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)

        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)

        agent_go._spawn_via_herdr_agent(
            tmp_path, prompt_body="test prompt", model="minimax-m3:cloud"
        )
        attach_calls = [c for c in captured if "attach" in c]
        assert attach_calls == []


# ---------------------------------------------------------------------------
# _should_auto_attach
# ---------------------------------------------------------------------------


class TestShouldAutoAttach:
    """`_should_auto_attach` returns True only when stdout is a TTY
    AND the env var is not set."""

    def test_env_var_set_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setenv("AGENT_GO_NO_AUTO_ATTACH", "1")
        assert agent_go._should_auto_attach() is False

    def test_env_var_truthy_values_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        for value in ("1", "true", "TRUE", "yes", "on", "True"):
            monkeypatch.setenv("AGENT_GO_NO_AUTO_ATTACH", value)
            assert agent_go._should_auto_attach() is False, f"value {value!r} should disable"

    def test_no_tty_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)
        assert agent_go._should_auto_attach() is False

    def test_tty_and_no_env_var_enables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.delenv("AGENT_GO_NO_AUTO_ATTACH", raising=False)
        assert agent_go._should_auto_attach() is True
