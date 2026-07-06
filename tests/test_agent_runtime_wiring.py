"""Tests for the `--runtime` / `--base-url` / `--api-key-env` wiring
in `agent_claude.py` and `agent_fleet.py`.

Run with `python -m pytest tests/test_agent_runtime_wiring.py -v`.
If pytest is not installed: `pip install -r requirements-dev.txt`.

Background. `agent-claude` and `agent-fleet` were wired into the
new runtime/provider layer in commit 2. Both commands now accept
`--runtime {claude,ollama,openai-compatible}` and route the
spawn argv / env through `_runtime.build_spawn_args()`. The
herdr and treehouse backends are still claude-only (herdr's
`agent start` is hardcoded to call the claude CLI via its
integration hook); the openai-compatible and ollama runtimes
route to direct spawn.

These tests pin down:

  - `--runtime` parses on both commands and lands in `args.runtime`.
  - `agent_claude._resolve_full_runtime` honours the CLI > env >
    config > default order.
  - `agent_fleet._resolve_backend` falls back to `none` when the
    requested backend is unavailable (e.g. `--runtime ollama`
    cannot use herdr).
  - The spawn argv for the `ollama` runtime contains `ollama run`
    and the model name; the spawn argv for the `claude` and
    `openai-compatible` runtimes contains `--model <model>`.
  - The `openai-compatible` runtime injects `ANTHROPIC_BASE_URL`
    and `ANTHROPIC_AUTH_TOKEN` into the child's env.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Make scripts/python/ importable.
_HERE = Path(__file__).resolve().parent
_PYTHON_SRC = _HERE.parent / "scripts" / "python"
if str(_PYTHON_SRC) not in sys.path:
    sys.path.insert(0, str(_PYTHON_SRC))

import agent_claude  # noqa: E402
import agent_fleet  # noqa: E402
import runtime as _runtime  # noqa: E402
from runtime import Runtime, build_spawn_args  # noqa: E402


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


class TestAgentClaudeArgparse:
    """`agent-claude --runtime`, `--base-url`, `--api-key-env`
    parse into the right `args` attributes."""

    def test_runtime_flag_parses(self) -> None:
        parser = agent_claude._build_argparser()
        args = parser.parse_args(["--runtime", "ollama"])
        assert args.runtime == "ollama"

    def test_runtime_choices_validated(self) -> None:
        """An unknown runtime name is rejected at argparse — we
        never reach resolution with garbage."""
        parser = agent_claude._build_argparser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--runtime", "gemini"])

    def test_base_url_and_api_key_env_parse(self) -> None:
        parser = agent_claude._build_argparser()
        args = parser.parse_args([
            "--runtime", "openai-compatible",
            "--base-url", "http://localhost:1234/v1",
            "--api-key-env", "MY_KEY",
        ])
        assert args.runtime == "openai-compatible"
        assert args.base_url == "http://localhost:1234/v1"
        assert args.api_key_env == "MY_KEY"

    def test_backend_still_parses_orthogonally(self) -> None:
        """`--backend` is the orchestrator (herdr / claude / ollama
        / none); it stays orthogonal to `--runtime`."""
        parser = agent_claude._build_argparser()
        args = parser.parse_args(["--backend", "herdr", "--runtime", "ollama"])
        assert args.backend == "herdr"
        assert args.runtime == "ollama"


class TestAgentFleetArgparse:
    """`agent-fleet --runtime`, `--base-url`, `--api-key-env`
    parse into the right `args` attributes."""

    def test_runtime_flag_parses(self) -> None:
        parser = agent_fleet._build_argparser()
        args = parser.parse_args(["3", "--runtime", "ollama"])
        assert args.runtime == "ollama"

    def test_runtime_choices_validated(self) -> None:
        parser = agent_fleet._build_argparser()
        with pytest.raises(SystemExit):
            parser.parse_args(["3", "--runtime", "gemini"])

    def test_base_url_and_api_key_env_parse(self) -> None:
        parser = agent_fleet._build_argparser()
        args = parser.parse_args([
            "2",
            "--runtime", "openai-compatible",
            "--base-url", "http://localhost:1234/v1",
            "--api-key-env", "MY_KEY",
        ])
        assert args.runtime == "openai-compatible"
        assert args.base_url == "http://localhost:1234/v1"
        assert args.api_key_env == "MY_KEY"

    def test_backend_still_parses_orthogonally(self) -> None:
        parser = agent_fleet._build_argparser()
        args = parser.parse_args(["2", "--backend", "herdr", "--runtime", "ollama"])
        assert args.backend == "herdr"
        assert args.runtime == "ollama"


# ---------------------------------------------------------------------------
# agent_claude._resolve_full_runtime
# ---------------------------------------------------------------------------


class TestAgentClaudeResolveRuntime:
    """`agent_claude._resolve_full_runtime` follows the
    CLI > env > config > default order, the same as
    `runtime.resolve_runtime` / `runtime.resolve_model`."""

    def test_cli_runtime_and_model_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_RUNTIME", raising=False)
        monkeypatch.delenv("AGENT_MODEL", raising=False)
        runtime = agent_claude._resolve_full_runtime(
            cli_runtime="ollama",
            cli_model="qwen2.5:7b",
            cli_base_url=None,
            cli_api_key_env=None,
        )
        assert runtime.name == "ollama"
        assert runtime.model == "qwen2.5:7b"
        assert runtime.base_url is None
        assert runtime.api_key_env is None

    def test_env_runtime_wins_over_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AGENT_RUNTIME", "ollama")
        # Drop a config file that says `default = "openai-compatible"`.
        cfg = tmp_path / "config.toml"
        cfg.write_text('[runtime]\ndefault = "openai-compatible"\n')
        monkeypatch.setattr(_runtime, "CONFIG_PATH", cfg)
        runtime = agent_claude._resolve_full_runtime(
            cli_runtime=None, cli_model=None, cli_base_url=None, cli_api_key_env=None
        )
        assert runtime.name == "ollama"

    def test_default_runtime_when_nothing_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_RUNTIME", raising=False)
        monkeypatch.delenv("AGENT_MODEL", raising=False)
        runtime = agent_claude._resolve_full_runtime(
            cli_runtime=None, cli_model=None, cli_base_url=None, cli_api_key_env=None
        )
        assert runtime.name == _runtime.DEFAULT_RUNTIME  # claude
        assert runtime.model == _runtime.DEFAULT_MODELS["claude"]  # opus

    def test_base_url_passthrough(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_RUNTIME", raising=False)
        monkeypatch.delenv("AGENT_MODEL", raising=False)
        runtime = agent_claude._resolve_full_runtime(
            cli_runtime="openai-compatible",
            cli_model="minimax-m3:cloud",
            cli_base_url="http://localhost:1234/v1",
            cli_api_key_env="MY_KEY",
        )
        assert runtime.base_url == "http://localhost:1234/v1"
        assert runtime.api_key_env == "MY_KEY"


# ---------------------------------------------------------------------------
# agent_claude spawn paths
# ---------------------------------------------------------------------------


class TestAgentClaudeSpawnPaths:
    """The spawn functions build the right argv and pass the right
    env to subprocess.run. We assert by intercepting
    `subprocess.run` / `run_command` and inspecting both."""

    def test_ollama_runtime_uses_ollama_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`agent-claude --runtime ollama` -> `ollama run <model>`."""
        # Drop a fake ollama binary on PATH.
        fake = tmp_path / "ollama.exe"
        fake.write_bytes(b"MZ\x00")

        captured: list = []

        def _fake_run(argv, **kwargs):  # noqa: ANN001
            captured.append((list(argv), kwargs))
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("agent_claude.run_command", _fake_run)
        runtime = _runtime.Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        rc = agent_claude._spawn_claude(tmp_path, runtime)
        assert rc == 0
        # The argv contains the resolved ollama path and `run <model>`.
        assert len(captured) == 1
        argv, kwargs = captured[0]
        assert "ollama" in argv[0]
        assert "run" in argv
        assert "minimax-m3:cloud" in argv

    def test_claude_runtime_uses_claude(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`agent-claude --runtime claude` -> `claude --model <model>`."""
        fake = tmp_path / "claude.cmd"
        fake.write_text("@echo off\r\n")
        # Put tmp_path on PATH so `resolve_executable("claude")` finds it.
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
        # Pre-create the prompt file the spawn reads.
        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)
        (tmp_path / AGENT_DIR_NAME / "SYSTEM_PROMPT.md").write_text("prompt")

        captured: list = []

        def _fake_run(argv, **kwargs):  # noqa: ANN001
            captured.append((list(argv), kwargs))
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("agent_claude.run_command", _fake_run)
        runtime = _runtime.Runtime(name="claude", model="opus", source="test")
        rc = agent_claude._spawn_claude(tmp_path, runtime)
        assert rc == 0
        argv, kwargs = captured[0]
        assert "claude" in argv[0]
        assert "--model" in argv
        assert "opus" in argv

    def test_openai_compatible_injects_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """`openai-compatible` -> `claude --model <model>` with
        `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` injected."""
        fake = tmp_path / "claude.cmd"
        fake.write_text("@echo off\r\n")
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)
        (tmp_path / AGENT_DIR_NAME / "SYSTEM_PROMPT.md").write_text("prompt")

        monkeypatch.setenv("MY_OPENAI_KEY", "sk-test-1234")
        captured: list = []

        def _fake_run(argv, **kwargs):  # noqa: ANN001
            captured.append((list(argv), kwargs))
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("agent_claude.run_command", _fake_run)
        runtime = _runtime.Runtime(
            name="openai-compatible",
            model="minimax-m3:cloud",
            base_url="http://localhost:1234/v1",
            api_key_env="MY_OPENAI_KEY",
            source="test",
        )
        rc = agent_claude._spawn_claude(tmp_path, runtime)
        assert rc == 0
        argv, kwargs = captured[0]
        # The env dict is passed to run_command and contains the overrides.
        assert "env" in kwargs
        env = kwargs["env"]
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:1234/v1"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-test-1234"

    def test_claude_runtime_no_env_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The `claude` runtime does NOT inject any env overrides."""
        fake = tmp_path / "claude.cmd"
        fake.write_text("@echo off\r\n")
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
        from scan_repo import AGENT_DIR_NAME
        (tmp_path / AGENT_DIR_NAME).mkdir(parents=True, exist_ok=True)
        (tmp_path / AGENT_DIR_NAME / "SYSTEM_PROMPT.md").write_text("prompt")

        captured: list = []

        def _fake_run(argv, **kwargs):  # noqa: ANN001
            captured.append((list(argv), kwargs))
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("agent_claude.run_command", _fake_run)
        runtime = _runtime.Runtime(name="claude", model="opus", source="test")
        agent_claude._spawn_claude(tmp_path, runtime)
        argv, kwargs = captured[0]
        # `env` is None for plain claude (no overrides).
        assert kwargs.get("env") is None


# ---------------------------------------------------------------------------
# agent_fleet._resolve_backend
# ---------------------------------------------------------------------------


class TestAgentFleetResolveBackend:
    """`_resolve_backend` picks the right backend given the
    requested backend and the runtime."""

    def test_claude_runtime_prefers_herdr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the `claude` runtime and all tools available,
        `auto` resolves to `herdr`."""
        monkeypatch.setattr(agent_fleet, "_herdr_available", lambda: True)
        monkeypatch.setattr(agent_fleet, "_herdr_server_running", lambda: True)
        monkeypatch.setattr(agent_fleet, "_claude_available", lambda: True)
        monkeypatch.setattr(agent_fleet, "_treehouse_available", lambda: True)
        runtime = Runtime(name="claude", model="opus", source="test")
        assert agent_fleet._resolve_backend("auto", runtime) == "herdr"

    def test_ollama_runtime_falls_back_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `ollama` runtime cannot use herdr or treehouse
        (both are claude-only by contract). `auto` resolves to
        `none`."""
        monkeypatch.setattr(agent_fleet, "_herdr_available", lambda: True)
        monkeypatch.setattr(agent_fleet, "_herdr_server_running", lambda: True)
        monkeypatch.setattr(agent_fleet, "_claude_available", lambda: True)
        monkeypatch.setattr(agent_fleet, "_treehouse_available", lambda: True)
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        assert agent_fleet._resolve_backend("auto", runtime) == "none"

    def test_openai_compatible_runtime_falls_back_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same for `openai-compatible`: herdr and treehouse
        are claude-only."""
        monkeypatch.setattr(agent_fleet, "_herdr_available", lambda: True)
        monkeypatch.setattr(agent_fleet, "_herdr_server_running", lambda: True)
        monkeypatch.setattr(agent_fleet, "_claude_available", lambda: True)
        runtime = Runtime(name="openai-compatible", model="minimax-m3:cloud", source="test")
        assert agent_fleet._resolve_backend("auto", runtime) == "none"

    def test_explicit_backend_returned_verbatim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the user passes `--backend=herdr`, we return that
        even if it would not be picked by `auto`."""
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        assert agent_fleet._resolve_backend("herdr", runtime) == "herdr"


# ---------------------------------------------------------------------------
# agent_fleet._spawn_none
# ---------------------------------------------------------------------------


class TestAgentFleetSpawnNone:
    """`_spawn_none` is the only fleet backend that works for
    all three runtimes (no herdr / treehouse dependency). It
    uses `subprocess.Popen` with the env overrides."""

    def test_ollama_runtime_spawns_ollama(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = tmp_path / "ollama.exe"
        fake.write_bytes(b"MZ\x00")
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
        captured: list = []

        class _FakePopen:
            def __init__(self, argv, **kwargs):  # noqa: ANN001
                captured.append((list(argv), kwargs))
                self.pid = 1234

        monkeypatch.setattr(agent_fleet.subprocess, "Popen", _FakePopen)
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        spawned = agent_fleet._spawn_none(tmp_path, 1, "code", runtime, "")
        assert len(spawned) == 1
        argv, kwargs = captured[0]
        # The resolved ollama path is argv[0].
        assert "ollama" in argv[0]
        assert "--model" in argv
        assert "minimax-m3:cloud" in argv
        # No env overrides for ollama.
        assert kwargs.get("env") is None

    def test_openai_compatible_runtime_injects_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        fake = tmp_path / "claude.cmd"
        fake.write_text("@echo off\r\n")
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))

        monkeypatch.setenv("MY_KEY", "sk-test-5678")
        captured: list = []

        class _FakePopen:
            def __init__(self, argv, **kwargs):  # noqa: ANN001
                captured.append((list(argv), kwargs))
                self.pid = 5678

        monkeypatch.setattr(agent_fleet.subprocess, "Popen", _FakePopen)
        runtime = Runtime(
            name="openai-compatible",
            model="minimax-m3:cloud",
            base_url="http://localhost:1234/v1",
            api_key_env="MY_KEY",
            source="test",
        )
        spawned = agent_fleet._spawn_none(tmp_path, 1, "code", runtime, "")
        assert len(spawned) == 1
        argv, kwargs = captured[0]
        # The env dict is passed to Popen and contains the overrides.
        assert "env" in kwargs
        env = kwargs["env"]
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:1234/v1"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-test-5678"

    def test_no_runner_writes_prompts_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When the requested runner is not on PATH, we still
        write the prompts but report rc=127 for each agent."""
        monkeypatch.setattr(agent_fleet, "first_executable", lambda names: None)
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        spawned = agent_fleet._spawn_none(tmp_path, 2, "code", runtime, "")
        assert len(spawned) == 2
        for entry in spawned:
            assert entry["rc"] == 127
            assert "not on PATH" in entry["error"]


# ---------------------------------------------------------------------------
# run_command accepts env=
# ---------------------------------------------------------------------------


class TestRunCommandEnv:
    """`utils.run_command` accepts an `env=` kwarg and forwards
    it to subprocess.run. This is the contract the openai-compatible
    spawn path depends on."""

    def test_run_command_with_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from utils import run_command
        captured: list = []

        def _fake_run(*args, **kwargs):  # noqa: ANN001
            captured.append(kwargs)
            return subprocess.CompletedProcess(
                args=args[0], returncode=0, stdout="ok", stderr=""
            )

        monkeypatch.setattr("utils.subprocess.run", _fake_run)
        rc = run_command(["echo", "hi"], env={"FOO": "bar"})
        assert rc.returncode == 0
        assert captured[0]["env"]["FOO"] == "bar"

    def test_run_command_without_env_uses_environ(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from utils import run_command
        captured: list = []

        def _fake_run(*args, **kwargs):  # noqa: ANN001
            captured.append(kwargs)
            return subprocess.CompletedProcess(
                args=args[0], returncode=0, stdout="ok", stderr=""
            )

        monkeypatch.setattr("utils.subprocess.run", _fake_run)
        run_command(["echo", "hi"])
        # No `env` kwarg was passed to run_command, so subprocess.run
        # sees no override and inherits the parent env.
        assert "env" not in captured[0]
