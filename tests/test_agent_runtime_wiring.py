"""Tests for the `--runtime` / `--base-url` / `--api-key-env` wiring
in `agent_claude.py` and `agent_fleet.py`.

Run with `python -m pytest tests/test_agent_runtime_wiring.py -v`.
If pytest is not installed: `pip install -r requirements-dev.txt`.

Background. `agent-claude` and `agent-fleet` were wired into the
new runtime/provider layer in commit 2. Both commands now accept
`--runtime {claude,ollama,ollama-chat,openai-compatible}` and
route the spawn argv / env through `_runtime.build_spawn_args()`.
The herdr and treehouse backends are still claude-only (herdr's
`agent start` is hardcoded to call the claude CLI via its
integration hook); the openai-compatible, ollama, and ollama-chat
runtimes route to direct spawn.

These tests pin down:

  - `--runtime` parses on both commands and lands in `args.runtime`.
  - `agent_claude._resolve_full_runtime` honours the CLI > env >
    config > default order.
  - `agent_fleet._resolve_backend` falls back to `none` when the
    requested backend is unavailable (e.g. `--runtime ollama`
    cannot use herdr).
  - The spawn argv for the `ollama` runtime contains `claude
    --model <model>` plus the ollama env overrides (Claude-Code-
    via-ollama). The spawn argv for the `ollama-chat` runtime
    contains `ollama run` and the model name. The spawn argv for
    the `claude` and `openai-compatible` runtimes contains
    `claude --model <model>`.
  - The `ollama` and `openai-compatible` runtimes inject
    `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` into the
    child's env. The `ollama-chat` runtime does not (it is plain
    `ollama run`).
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
import agent_go  # noqa: E402
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

    def test_ollama_runtime_uses_claude_via_ollama(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`agent-claude --runtime ollama` -> `claude --model <m>`
        with the ollama OpenAI-compatible env. The plain
        `ollama run` lives under `--runtime ollama-chat`."""
        # Drop a fake claude binary on PATH.
        fake = tmp_path / "claude.cmd"
        fake.write_text("@echo off\r\n")
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))

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
        # The argv contains the resolved claude path and the model.
        assert len(captured) == 1
        argv, kwargs = captured[0]
        assert "claude" in argv[0]
        assert "--model" in argv
        assert "minimax-m3:cloud" in argv
        # The ollama env overrides are injected.
        env = kwargs.get("env") or {}
        assert env.get("ANTHROPIC_BASE_URL") == "http://localhost:11434"
        assert env.get("ANTHROPIC_AUTH_TOKEN") == "ollama"

    def test_ollama_chat_runtime_uses_ollama_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`agent-claude --runtime ollama-chat` -> `ollama run <model>`."""
        # Drop a fake ollama binary on PATH.
        fake = tmp_path / "ollama.exe"
        fake.write_bytes(b"MZ\x00")
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))

        captured: list = []

        def _fake_run(argv, **kwargs):  # noqa: ANN001
            captured.append((list(argv), kwargs))
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("agent_claude.run_command", _fake_run)
        runtime = _runtime.Runtime(name="ollama-chat", model="minimax-m3:cloud", source="test")
        rc = agent_claude._spawn_claude(tmp_path, runtime)
        assert rc == 0
        # The argv contains the resolved ollama path and `run <model>`.
        assert len(captured) == 1
        argv, kwargs = captured[0]
        assert "ollama" in argv[0]
        assert "run" in argv
        assert "minimax-m3:cloud" in argv
        # No env overrides for the chat runtime.
        env = kwargs.get("env")
        assert env is None or env == {}

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

    def test_ollama_runtime_spawns_claude_via_ollama(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`agent-fleet --runtime ollama` -> `claude --model <m>`
        with the ollama OpenAI-compatible env. Same shape as
        `agent-claude`."""
        fake = tmp_path / "claude.cmd"
        fake.write_text("@echo off\r\n")
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
        # The resolved claude path is argv[0].
        assert "claude" in argv[0]
        assert "--model" in argv
        assert "minimax-m3:cloud" in argv
        # The ollama env overrides are injected.
        env = kwargs.get("env") or {}
        assert env.get("ANTHROPIC_BASE_URL") == "http://localhost:11434"
        assert env.get("ANTHROPIC_AUTH_TOKEN") == "ollama"

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
# agent-claude / agent-fleet herdr agent_name_taken retry
# ---------------------------------------------------------------------------


class TestAgentClaudeAndFleetHerdrRetry:
    """`agent-claude` and `agent-fleet` retry on
    `herdr agent_name_taken` (defensive: an earlier
    agent-go session may have left a stale `primary`
    on the server)."""

    def _make_run_command_fake(
        self, agent_start_attempts_to_fail: dict[int, str]
    ):
        """Return a fake `run_command` (and a list of all
        `herdr agent start` argv sequences) that fails
        the given `agent start` attempts with the
        `agent_name_taken` marker, and succeeds for the
        rest. Worktree-create calls always succeed.
        """
        agent_start_count: list[int] = [0]
        calls: list[list[str]] = []

        def _fake_run_command(argv, **kwargs):  # noqa: ANN001
            calls.append(list(argv))
            if "agent" in argv and "start" in argv:
                agent_name = argv[3] if len(argv) > 3 else "?"
                attempt_idx = agent_start_count[0]
                agent_start_count[0] += 1
                if attempt_idx in agent_start_attempts_to_fail:
                    return subprocess.CompletedProcess(
                        args=argv,
                        returncode=1,
                        stdout="",
                        stderr=(
                            f"error: {agent_start_attempts_to_fail[attempt_idx]}: "
                            f"{agent_name} is already used"
                        ),
                    )
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout="", stderr=""
                )
            # Worktree create: succeed.
            if "worktree" in argv and "create" in argv:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout='{"worktree_created":{}}',
                    stderr="",
                )
            # Integration install: succeed.
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="installed", stderr=""
            )

        return _fake_run_command, calls

    def test_agent_claude_retries_with_unique_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`agent-claude`'s herdr spawn retries `primary` ->
        `primary-2` -> `primary-3` on `agent_name_taken`."""
        fake, calls = self._make_run_command_fake(
            {0: "agent_name_taken", 1: "agent_name_taken"}
        )
        monkeypatch.setattr(agent_claude, "run_command", fake)
        # Make herdr + claude available so we don't take the
        # missing-binary fallback.
        claude_path = tmp_path / "claude.cmd"
        claude_path.write_text("@echo off\r\n")
        herdr_path = tmp_path / "herdr.cmd"
        herdr_path.write_text("@echo off\r\n")

        def _resolve(name: str) -> str | None:
            if name == "claude":
                return str(claude_path)
            if name == "herdr":
                return str(herdr_path)
            return None

        monkeypatch.setattr(agent_claude, "resolve_executable", _resolve)
        # A real .agent dir to hold the prompt.
        agent_dir = tmp_path / ".agent"
        agent_dir.mkdir(exist_ok=True)
        prompt_path = agent_dir / "SYSTEM_PROMPT.md"
        prompt_path.write_text("test prompt body", encoding="utf-8")
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        rc = agent_claude._spawn_herdr_agent(
            tmp_path, prompt_path, runtime, agent_name="primary"
        )
        assert rc == 0
        agent_calls = [a for a in calls if "agent" in a and "start" in a]
        assert len(agent_calls) == 3
        assert agent_calls[0][3] == "primary"
        assert agent_calls[1][3] == "primary-2"
        assert agent_calls[2][3] == "primary-3"

    def test_agent_fleet_retries_with_unique_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`agent-fleet` retries the per-agent name on
        `agent_name_taken` for a single fleet invocation."""
        fake, calls = self._make_run_command_fake(
            {0: "agent_name_taken"}
        )
        monkeypatch.setattr(agent_fleet, "run_command", fake)
        claude_path = tmp_path / "claude.cmd"
        claude_path.write_text("@echo off\r\n")
        herdr_path = tmp_path / "herdr.cmd"
        herdr_path.write_text("@echo off\r\n")

        def _resolve(names: list[str]) -> str | None:
            for n in names:
                if n == "claude":
                    return str(claude_path)
                if n == "herdr":
                    return str(herdr_path)
            return None

        monkeypatch.setattr(agent_fleet, "first_executable", _resolve)
        monkeypatch.setattr(agent_fleet, "_herdr_available", lambda: True)
        monkeypatch.setattr(agent_fleet, "_claude_available", lambda: True)
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        # Spawn a single agent (`n=1`) to keep the assertions tight.
        # Use worktree=False to skip the worktree-create branch.
        spawned = agent_fleet._spawn_herdr(
            tmp_path, 1, "code", False, runtime, ""
        )
        assert len(spawned) == 1
        assert spawned[0]["rc"] == 0
        # The agent's name should be `fleet-1-2` (the retry) since
        # `fleet-1` was taken.
        assert spawned[0]["name"] == "fleet-1-2"
        agent_calls = [a for a in calls if "agent" in a and "start" in a]
        assert len(agent_calls) == 2
        assert agent_calls[0][3] == "fleet-1"
        assert agent_calls[1][3] == "fleet-1-2"



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


# ---------------------------------------------------------------------------
# agent-go herdr agent_name_taken retry
# ---------------------------------------------------------------------------


class TestAgentGoHerdrRetry:
    """`agent-go`'s herdr spawn retries with a unique name on
    `agent_name_taken`. We mock `subprocess.run` to simulate
    herdr's behaviour and assert the retry path uses the
    right names."""

    def _make_herdr_fake(self, agent_start_attempts_to_fail: dict[int, str]):
        """Return a fake `subprocess.run` that fails with
        `agent_name_taken: <name> is already used` for the
        given `agent start` attempt indices, and succeeds
        for the rest. Worktree-create calls always succeed
        (we don't care about the worktree path in these
        tests; we just want the agent-name retry path)."""
        agent_start_count: list[int] = [0]

        def _fake_run(argv, **kwargs):  # noqa: ANN001
            # Only the `agent start` subcommand takes an agent
            # name. We treat the worktree create call as always
            # succeeding with a JSON envelope that has no path,
            # which makes _spawn_via_herdr_agent fall back to
            # `str(repo)` for worktree_path.
            if "agent" in argv and "start" in argv:
                agent_name = argv[3] if len(argv) > 3 else "?"
                attempt_idx = agent_start_count[0]
                agent_start_count[0] += 1
                if attempt_idx in agent_start_attempts_to_fail:
                    return subprocess.CompletedProcess(
                        args=argv,
                        returncode=1,
                        stdout="",
                        stderr=(
                            f"error: {agent_start_attempts_to_fail[attempt_idx]}: "
                            f"{agent_name} is already used"
                        ),
                    )
                # Success: emit a `agent_started` JSON envelope.
                payload = (
                    '{"agent_started":{"agent":"' + agent_name + '",'
                    '"cwd":"C:\\\\repo","argv":[]}}'
                )
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout=payload, stderr=""
                )
            # Worktree create: succeed with a JSON envelope that
            # has no path so the function falls back to `str(repo)`.
            if "worktree" in argv and "create" in argv:
                payload = '{"worktree_created":{}}'
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout=payload, stderr=""
                )
            # Any other call (e.g. _auto_attach or _spawn_direct):
            # succeed.
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="", stderr=""
            )

        return _fake_run

    def test_retries_with_unique_name_on_collision(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """First two attempts hit `agent_name_taken`; the third
        succeeds. The function should use `primary`, `primary-2`,
        and `primary-3` for the three attempts, then return 0."""
        fake = self._make_herdr_fake({0: "agent_name_taken", 1: "agent_name_taken"})
        # Track every `agent start` call.
        agent_calls: list = []
        original = fake

        def _tracker(argv, **kwargs):  # noqa: ANN001
            if "agent" in argv and "start" in argv:
                agent_calls.append(list(argv))
            return original(argv, **kwargs)

        monkeypatch.setattr("agent_go.subprocess.run", _tracker)
        claude_path = tmp_path / "claude.cmd"
        claude_path.write_text("@echo off\r\n")
        herdr_path = tmp_path / "herdr.cmd"
        herdr_path.write_text("@echo off\r\n")

        def _resolve(name: str) -> str | None:
            if name == "claude":
                return str(claude_path)
            if name == "herdr":
                return str(herdr_path)
            return None

        monkeypatch.setattr("agent_go.resolve_executable", _resolve)
        runtime = _runtime.Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        spawn_cmd = ["claude", "--model", "minimax-m3:cloud"]
        spawn_env: dict = {}
        prompt = "test prompt body"
        rc = agent_go._spawn_via_herdr_agent(
            tmp_path, prompt, runtime, spawn_cmd, spawn_env, auto_attach=False
        )
        assert rc == 0
        # Three herdr `agent start` calls.
        assert len(agent_calls) == 3
        assert agent_calls[0][3] == "primary"
        assert agent_calls[1][3] == "primary-2"
        assert agent_calls[2][3] == "primary-3"

    def test_exhausts_retries_falls_back_to_direct(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """All 8 attempts fail with `agent_name_taken`; the
        function should fall back to `_spawn_direct`."""
        fake = self._make_herdr_fake({i: "agent_name_taken" for i in range(20)})
        agent_calls: list = []
        direct_calls: list = []

        def _tracker(argv, **kwargs):  # noqa: ANN001
            if "agent" in argv and "start" in argv:
                agent_calls.append(list(argv))
            else:
                direct_calls.append(list(argv))
            return fake(argv, **kwargs)

        monkeypatch.setattr("agent_go.subprocess.run", _tracker)
        claude_path = tmp_path / "claude.cmd"
        claude_path.write_text("@echo off\r\n")
        herdr_path = tmp_path / "herdr.cmd"
        herdr_path.write_text("@echo off\r\n")

        def _resolve(name: str) -> str | None:
            if name == "claude":
                return str(claude_path)
            if name == "herdr":
                return str(herdr_path)
            return None

        monkeypatch.setattr("agent_go.resolve_executable", _resolve)
        runtime = _runtime.Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        spawn_cmd = ["claude", "--model", "minimax-m3:cloud"]
        spawn_env: dict = {}
        prompt = "test prompt body"
        rc = agent_go._spawn_via_herdr_agent(
            tmp_path, prompt, runtime, spawn_cmd, spawn_env, auto_attach=False
        )
        # We made 8 herdr attempts then fell back to direct. The
        # rc is whatever direct returned (0 in our fake).
        assert rc == 0
        # 8 herdr `agent start` calls.
        assert len(agent_calls) == 8
        # The 8 names should be primary, primary-2, ..., primary-5,
        # then 3 shortid names.
        assert agent_calls[0][3] == "primary"
        assert agent_calls[1][3] == "primary-2"
        assert agent_calls[4][3] == "primary-5"


# ---------------------------------------------------------------------------
# agent-go pre-launch output block
# ---------------------------------------------------------------------------


class TestAgentGoPrelaunchOutput:
    """The pre-launch output block must show the resolved
    runtime / mode / model / base_url / backend / command /
    agent / cwd in the documented order. The first three
    lines (runtime / mode / model) are printed before the
    spawn; the rest are printed after a successful herdr
    spawn."""

    def test_print_prompt_includes_seven_line_block(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """`--print-prompt` resolves runtime + model + mode
        and prints the pre-launch block at the top."""
        rc = agent_go.main([
            "--print-prompt",
            "--no-bootstrap",
            "--runtime", "ollama",
            "--model", "minimax-m3:cloud",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        err = captured.err
        assert "agent-workbench: runtime:      ollama" in err
        assert "agent-workbench: runtime mode: claude-via-ollama" in err
        assert "agent-workbench: model:        minimax-m3:cloud" in err
        # The prompt body is on stdout.
        assert "Global toolkit instructions" in captured.out

    def test_ollama_runtime_command_is_claude_with_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`--runtime ollama` builds a `claude --model <m>`
        command and injects the ollama env into the child.
        Asserted by inspecting `build_spawn_args`."""
        runtime = _runtime.Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        cmd, env = _runtime.build_spawn_args(runtime)
        assert cmd == ["claude", "--model", "minimax-m3:cloud"]
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"

    def test_ollama_chat_runtime_command_is_ollama_run(self) -> None:
        """`--runtime ollama-chat` builds the plain `ollama run`
        command with no env overrides."""
        runtime = _runtime.Runtime(name="ollama-chat", model="minimax-m3:cloud", source="test")
        cmd, env = _runtime.build_spawn_args(runtime)
        assert cmd == ["ollama", "run", "minimax-m3:cloud"]
        assert env == {}


# ---------------------------------------------------------------------------
# agent-go setup flow
# ---------------------------------------------------------------------------


class TestAgentGoSetup:
    """`agent-go --setup` writes a valid config. We test the
    terminal-prompt path (lavish-axi absent) by feeding stdin
    and asserting the resulting file parses back."""

    def test_setup_writes_valid_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Drive the terminal prompt path with a fixed
        sequence of answers. The resulting config file at
        the test path must parse back via `load_config`
        and contain the user's choices."""
        config_path = tmp_path / "config.toml"
        # Sequence of answers for the prompts:
        # 1. default runtime: ollama
        # 2. model: minimax-m3:cloud (just hit enter)
        # 3. ollama mode: claude
        # 4. backend: herdr
        # 5. lavish-axi for setup? n
        answers = iter(["ollama\n", "\n", "claude\n", "herdr\n", "n\n"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        # lavish-axi is not on PATH -> terminal prompts.
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: None)
        rc = agent_go._run_setup_interactive(config_path)
        assert rc == 0
        # The file exists and is parseable.
        assert config_path.is_file()
        cfg = _runtime.load_config(path=config_path)
        assert cfg["runtime"]["default"] == "ollama"
        assert cfg["ollama"]["mode"] == "claude"
        assert cfg["backend"]["default"] == "herdr"
        assert cfg["ui"]["setup"] == "terminal"

    def test_setup_respects_existing_file_overwrite(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """If the file exists and the user says 'no' to
        overwrite, the setup returns 1 and the file is
        unchanged."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("# existing content\n[runtime]\ndefault = \"claude\"\n", encoding="utf-8")
        # The "overwrite?" prompt gets a 'n'.
        answers = iter(["n\n"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: None)
        rc = agent_go._run_setup_interactive(config_path)
        assert rc == 1
        # The file is unchanged.
        assert config_path.read_text(encoding="utf-8").startswith("# existing content")

    def test_setup_argparse_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--setup` parses on the agent-go argparser."""
        parser = agent_go._build_argparser()
        args = parser.parse_args(["--setup"])
        assert args.setup is True

    def test_setup_writes_self_documenting_comments(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The written file includes comments so the user can
        read it and understand the choices without re-running
        `--setup`."""
        config_path = tmp_path / "config.toml"
        answers = iter(["claude\n", "\n", "herdr\n", "n\n"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        monkeypatch.setattr("agent_go.resolve_executable", lambda name: None)
        agent_go._run_setup_interactive(config_path)
        text = config_path.read_text(encoding="utf-8")
        assert "agent-workbench configuration" in text
        assert "[runtime]" in text
        assert "[backend]" in text
        assert "[ui]" in text
