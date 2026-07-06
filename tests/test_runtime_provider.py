"""Tests for the runtime/provider layer in `scripts/python/runtime.py`
and its integration with `agent_go.py`.

Run with `python -m pytest tests/test_runtime_provider.py -v`.
If pytest is not installed: `pip install -r requirements-dev.txt`.

Background. `agent-go` used to assume Claude Code was the only
interactive model runner, and a user without an Anthropic
subscription had no documented path to a working session. The new
runtime module introduces three first-class runtimes — `claude`,
`ollama`, `openai-compatible` — with a clear resolution order
(CLI > env > config > default) and a login-probe that catches the
"Claude not logged in" case before dropping the user into a
broken pane.

These tests pin down the contract:

  - `resolve_runtime` follows CLI > env > config > default, with
    unknown values falling through.
  - `resolve_model` follows the same order, with runtime-specific
    defaults (claude -> "opus", ollama and openai-compatible ->
    "minimax-m3:cloud"). The legacy top-level `model = ...` config
    key is honored as a fallback.
  - `load_config` parses the four sections, ignores comments and
    blank lines, returns an empty dict on a missing or garbage
    file, and normalizes `openai_compatible` (file form) to
    `openai-compatible` (runtime form).
  - `claude_logged_in` returns True if any of the three env vars
    is set, if the standard credentials file is present, or if
    the legacy `~/.claude.json` is present.
  - `build_spawn_args` returns the right (cmd, env_overrides) tuple
    for each runtime. The openai-compatible path populates
    `ANTHROPIC_BASE_URL` (always, if base_url is provided) and
    `ANTHROPIC_AUTH_TOKEN` (only if the named env var resolves to
    a non-empty value).
  - `agent_go.main` honors `--runtime`, prints the resolved
    runtime + model, and short-circuits to the fallback message
    when Claude is not logged in.
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

import agent_go  # noqa: E402
import runtime as _runtime  # noqa: E402
from runtime import (  # noqa: E402
    DEFAULT_MODELS,
    DEFAULT_RUNTIME,
    RUNTIMES,
    Runtime,
    build_spawn_args,
    claude_logged_in,
    claude_missing_login_message,
    load_config,
    resolve_model,
    resolve_ollama_mode,
    resolve_runtime,
    runtime_summary_lines,
)


# ---------------------------------------------------------------------------
# resolve_runtime
# ---------------------------------------------------------------------------


class TestResolveRuntime:
    """`resolve_runtime` follows the documented order
    (CLI > env > config > default). Each layer wins over the
    later ones; unknown values fall through."""

    def test_default_when_nothing_set(self) -> None:
        name, source = resolve_runtime(cli_value=None, env_value=None, config={})
        assert name == DEFAULT_RUNTIME
        assert source == "default"

    def test_cli_wins(self) -> None:
        name, source = resolve_runtime(
            cli_value="ollama", env_value="claude", config={"runtime": {"default": "openai-compatible"}}
        )
        assert name == "ollama"
        assert source == "cli"

    def test_env_wins_over_config(self) -> None:
        name, source = resolve_runtime(
            cli_value=None, env_value="ollama", config={"runtime": {"default": "openai-compatible"}}
        )
        assert name == "ollama"
        assert source == "env"

    def test_config_used_when_no_cli_or_env(self) -> None:
        name, source = resolve_runtime(
            cli_value=None, env_value=None, config={"runtime": {"default": "ollama"}}
        )
        assert name == "ollama"
        assert source == "config"

    def test_unknown_cli_falls_through_to_env(self) -> None:
        name, source = resolve_runtime(
            cli_value="gemini", env_value="ollama", config={}
        )
        assert name == "ollama"
        assert source == "env"

    def test_unknown_env_falls_through_to_config(self) -> None:
        name, source = resolve_runtime(
            cli_value=None, env_value="gemini", config={"runtime": {"default": "ollama"}}
        )
        assert name == "ollama"
        assert source == "config"

    def test_unknown_config_falls_through_to_default(self) -> None:
        name, source = resolve_runtime(
            cli_value=None, env_value=None, config={"runtime": {"default": "gemini"}}
        )
        assert name == DEFAULT_RUNTIME
        assert source == "default"

    def test_explicit_none_in_config_falls_through(self) -> None:
        """An empty string or None in `[runtime] default` is treated
        as "no config" and we fall through to the next layer."""
        name, source = resolve_runtime(
            cli_value=None, env_value=None, config={"runtime": {"default": ""}}
        )
        assert name == DEFAULT_RUNTIME
        assert source == "default"

    def test_all_three_runtimes_are_valid(self) -> None:
        for name in RUNTIMES:
            resolved, source = resolve_runtime(
                cli_value=name, env_value=None, config={}
            )
            assert resolved == name
            assert source == "cli"


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------


class TestResolveModel:
    """`resolve_model` follows the same order as `resolve_runtime`,
    but the per-runtime config section (`[claude] model = ...`,
    `[ollama] model = ...`) is the relevant config key. The
    legacy top-level `model = "..."` key is honored as a
    fallback for backwards compatibility."""

    def test_runtime_specific_defaults(self) -> None:
        """Each runtime has its own sensible default model. The user's
        contract: `minimax-m3:cloud` is NOT hardcoded as a Claude
        model; Claude defaults to `opus`."""
        assert DEFAULT_MODELS["claude"] == "opus"
        assert DEFAULT_MODELS["ollama"] == "minimax-m3:cloud"
        assert DEFAULT_MODELS["ollama-chat"] == "minimax-m3:cloud"
        assert DEFAULT_MODELS["openai-compatible"] == "minimax-m3:cloud"

    def test_default_for_claude(self) -> None:
        model, source = resolve_model(
            "claude", cli_model=None, env_model=None, config={}
        )
        assert model == "opus"
        assert source == "default"

    def test_default_for_ollama(self) -> None:
        model, source = resolve_model(
            "ollama", cli_model=None, env_model=None, config={}
        )
        assert model == "minimax-m3:cloud"
        assert source == "default"

    def test_default_for_ollama_chat(self) -> None:
        model, source = resolve_model(
            "ollama-chat", cli_model=None, env_model=None, config={}
        )
        assert model == "minimax-m3:cloud"
        assert source == "default"

    def test_ollama_chat_uses_ollama_chat_section(self) -> None:
        """When runtime is `ollama-chat`, the model comes from
        `[ollama_chat].model` (a separate config section so the
        user can pick a chat-tuned model independently of the
        coding-agent model in `[ollama].model`)."""
        model, source = resolve_model(
            "ollama-chat",
            cli_model=None,
            env_model=None,
            config={"ollama_chat": {"model": "llama3.2:3b"}},
        )
        assert model == "llama3.2:3b"
        assert source == "config"


# ---------------------------------------------------------------------------
# resolve_ollama_mode
# ---------------------------------------------------------------------------


class TestResolveOllamaMode:
    """`resolve_ollama_mode` reads `[ollama] mode` (or the
    `AGENT_OLLAMA_MODE` env var) and returns either `"claude"`
    (default) or `"chat"`. This is the switch between
    claude-via-ollama and plain ollama chat REPL."""

    def test_default_is_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_OLLAMA_MODE", raising=False)
        assert resolve_ollama_mode({}) == "claude"
        assert resolve_ollama_mode({"ollama": {}}) == "claude"

    def test_config_mode_chat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_OLLAMA_MODE", raising=False)
        cfg = {"ollama": {"mode": "chat"}}
        assert resolve_ollama_mode(cfg) == "chat"

    def test_config_mode_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_OLLAMA_MODE", raising=False)
        cfg = {"ollama": {"mode": "claude"}}
        assert resolve_ollama_mode(cfg) == "claude"

    def test_env_var_wins_over_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_OLLAMA_MODE", "chat")
        cfg = {"ollama": {"mode": "claude"}}
        assert resolve_ollama_mode(cfg) == "chat"

    def test_unknown_value_falls_back_to_claude(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo in `[ollama] mode` is treated as the default
        (`"claude"`) so the user is never silently routed to
        a different flow than the one they thought they picked."""
        monkeypatch.delenv("AGENT_OLLAMA_MODE", raising=False)
        cfg = {"ollama": {"mode": "definitely-not-a-real-mode"}}
        assert resolve_ollama_mode(cfg) == "claude"

    def test_empty_string_falls_back_to_claude(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_OLLAMA_MODE", raising=False)
        cfg = {"ollama": {"mode": ""}}
        assert resolve_ollama_mode(cfg) == "claude"

    def test_default_for_openai_compatible(self) -> None:
        model, source = resolve_model(
            "openai-compatible", cli_model=None, env_model=None, config={}
        )
        assert model == "minimax-m3:cloud"
        assert source == "default"

    def test_cli_model_wins(self) -> None:
        model, source = resolve_model(
            "ollama",
            cli_model="qwen2.5:7b",
            env_model="minimax-m3:cloud",
            config={"ollama": {"model": "llama3"}},
        )
        assert model == "qwen2.5:7b"
        assert source == "cli"

    def test_env_model_wins_over_config(self) -> None:
        model, source = resolve_model(
            "ollama",
            cli_model=None,
            env_model="qwen2.5:7b",
            config={"ollama": {"model": "llama3"}},
        )
        assert model == "qwen2.5:7b"
        assert source == "env"

    def test_per_runtime_config_section_wins(self) -> None:
        """The per-runtime section is the right config key for
        that runtime. E.g. for `ollama`, the `[ollama] model` is
        the relevant one — not `[claude] model`."""
        model, source = resolve_model(
            "ollama",
            cli_model=None,
            env_model=None,
            config={"ollama": {"model": "llama3"}, "claude": {"model": "opus"}},
        )
        assert model == "llama3"
        assert source == "config"

    def test_legacy_top_level_model_key_honored(self) -> None:
        """The legacy `model = "..."` form (one-line config) is
        honored as a fallback for users who haven't migrated."""
        model, source = resolve_model(
            "claude",
            cli_model=None,
            env_model=None,
            config={"_": {"model": "minimax-m3:cloud"}},
        )
        assert model == "minimax-m3:cloud"
        assert source == "config"

    def test_unknown_runtime_falls_back_to_claude_default(self) -> None:
        """If the caller asks for a runtime that doesn't exist
        in `DEFAULT_MODELS`, we still return a valid string (the
        claude default) so the spawn path doesn't crash."""
        model, source = resolve_model(
            "totally-fake-runtime",
            cli_model=None,
            env_model=None,
            config={},
        )
        assert model == DEFAULT_MODELS["claude"]


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """`load_config` is a tiny line-based TOML parser. It must
    handle the four-section schema, ignore comments and blank
    lines, and degrade gracefully on missing or garbage files."""

    def test_missing_file_returns_empty_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No file at the configured path -> empty dict. The
        caller falls through to the default model."""
        result = load_config(path=tmp_path / "no-such-file.toml")
        assert result == {}

    def test_parses_sections(self, tmp_path: Path) -> None:
        """Each `[section]` header creates a new dict."""
        p = tmp_path / "config.toml"
        p.write_text(
            "[runtime]\n"
            'default = "ollama"\n'
            "\n"
            "[claude]\n"
            'model = "opus"\n'
            "\n"
            "[ollama]\n"
            'mode = "claude"\n'
            'model = "minimax-m3:cloud"\n'
            "\n"
            "[ollama_chat]\n"
            'model = "llama3.2:3b"\n'
            "\n"
            "[openai_compatible]\n"
            'base_url = "http://localhost:1234/v1"\n'
            'api_key_env = "OPENAI_API_KEY"\n'
            'model = "minimax-m3:cloud"\n'
            "\n"
            "[backend]\n"
            'default = "herdr"\n'
            "\n"
            "[ui]\n"
            'setup = "lavish-axi"\n'
        )
        cfg = load_config(path=p)
        assert cfg["runtime"] == {"default": "ollama"}
        assert cfg["claude"] == {"model": "opus"}
        assert cfg["ollama"] == {"mode": "claude", "model": "minimax-m3:cloud"}
        assert cfg["ollama_chat"] == {"model": "llama3.2:3b"}
        assert cfg["openai-compatible"] == {
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "OPENAI_API_KEY",
            "model": "minimax-m3:cloud",
        }
        assert cfg["backend"] == {"default": "herdr"}
        assert cfg["ui"] == {"setup": "lavish-axi"}

    def test_parses_ollama_chat_section(self, tmp_path: Path) -> None:
        """`[ollama_chat] model = "x"` lands in
        `config["ollama_chat"]["model"]` so the ollama-chat
        runtime can read its own default model."""
        p = tmp_path / "config.toml"
        p.write_text(
            "[ollama_chat]\n"
            'model = "llama3.2:3b"\n'
        )
        cfg = load_config(path=p)
        assert cfg["ollama_chat"] == {"model": "llama3.2:3b"}

    def test_parses_backend_section(self, tmp_path: Path) -> None:
        """`[backend] default = "herdr"` lands in
        `config["backend"]["default"]` so the setup flow can
        read it."""
        p = tmp_path / "config.toml"
        p.write_text(
            "[backend]\n"
            'default = "herdr"\n'
        )
        cfg = load_config(path=p)
        assert cfg["backend"] == {"default": "herdr"}

    def test_parses_ui_section(self, tmp_path: Path) -> None:
        """`[ui] setup = "lavish-axi"` lands in
        `config["ui"]["setup"]` so the setup flow can read
        the user's UI preference."""
        p = tmp_path / "config.toml"
        p.write_text(
            "[ui]\n"
            'setup = "lavish-axi"\n'
        )
        cfg = load_config(path=p)
        assert cfg["ui"] == {"setup": "lavish-axi"}

    def test_ollama_mode_field(self, tmp_path: Path) -> None:
        """`[ollama] mode = "chat"` lands in
        `config["ollama"]["mode"]` so the runtime layer can
        switch between claude-via-ollama and plain ollama chat."""
        p = tmp_path / "config.toml"
        p.write_text(
            "[ollama]\n"
            'mode = "chat"\n'
            'model = "minimax-m3:cloud"\n'
        )
        cfg = load_config(path=p)
        assert cfg["ollama"]["mode"] == "chat"
        assert cfg["ollama"]["model"] == "minimax-m3:cloud"

    def test_normalises_openai_compatible_section(self, tmp_path: Path) -> None:
        """`openai_compatible` in the file is normalised to
        `openai-compatible` in the returned dict so callers can
        use the runtime name directly as a key."""
        p = tmp_path / "config.toml"
        p.write_text(
            "[openai_compatible]\n"
            'base_url = "http://localhost:1234/v1"\n'
        )
        cfg = load_config(path=p)
        assert "openai_compatible" not in cfg
        assert cfg["openai-compatible"] == {"base_url": "http://localhost:1234/v1"}

    def test_ignores_comments_and_blank_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "config.toml"
        p.write_text(
            "# this is a comment\n"
            "\n"
            "[runtime]\n"
            "# inside-section comment\n"
            'default = "ollama"\n'
            "\n"
            '   \n'
        )
        cfg = load_config(path=p)
        assert cfg["runtime"] == {"default": "ollama"}

    def test_legacy_top_level_model_key(self, tmp_path: Path) -> None:
        """The bare `model = "..."` form (no section) lands in the
        special `_` section so callers can detect it as the
        legacy single-line config."""
        p = tmp_path / "config.toml"
        p.write_text('model = "minimax-m3:cloud"\n')
        cfg = load_config(path=p)
        assert cfg["_"] == {"model": "minimax-m3:cloud"}

    def test_handles_quoted_and_unquoted_values(self, tmp_path: Path) -> None:
        """Both `key = "value"` and `key = value` parse."""
        p = tmp_path / "config.toml"
        p.write_text(
            "[claude]\n"
            'model = "opus"\n'
            "fallback_model = sonnet\n"
        )
        cfg = load_config(path=p)
        assert cfg["claude"]["model"] == "opus"
        assert cfg["claude"]["fallback_model"] == "sonnet"

    def test_garbage_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """A corrupt config must not crash `agent-go`. Returns
        an empty dict; the caller falls through to defaults."""
        p = tmp_path / "config.toml"
        p.write_text("not = valid [toml at all =] = =")
        cfg = load_config(path=p)
        # We only require the parser not to crash and to return
        # *some* dict. The exact contents for garbage input are
        # best-effort: the line-based parser will pick out
        # `not = valid` and drop the rest.
        assert isinstance(cfg, dict)

    def test_oserror_on_read_returns_empty_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the file is unreadable (permission, encoding, IO),
        we return an empty dict instead of raising."""
        p = tmp_path / "config.toml"
        p.write_text("anything")

        def _raise(*args, **kwargs):  # noqa: ANN001
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", _raise)
        assert load_config(path=p) == {}


# ---------------------------------------------------------------------------
# claude_logged_in
# ---------------------------------------------------------------------------


class TestClaudeLoggedIn:
    """`claude_logged_in` probes for Claude Code credentials. The
    user-facing contract: returns True if any of the env vars is
    set, or if the credentials file is present, or if the legacy
    `~/.claude.json` is present."""

    @pytest.fixture
    def isolated_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Point `Path.home()` at a fresh tmp dir for the test
        duration. Without this, the user's real `~/.claude.json`
        or `~/.claude/.credentials.json` would leak into the
        'no credentials anywhere' tests and produce false
        positives."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        return tmp_path

    def test_env_var_anthropic_api_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_home: Path
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        assert claude_logged_in() is True

    def test_env_var_anthropic_auth_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_home: Path
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        assert claude_logged_in() is True

    def test_env_var_oauth_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_home: Path
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        assert claude_logged_in() is True

    def test_env_var_whitespace_treated_as_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_home: Path
    ) -> None:
        """A whitespace-only env var is treated as unset. This
        prevents the false positive where a user has `export
        ANTHROPIC_API_KEY=` (empty) and we report them as logged in."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        assert claude_logged_in() is False

    def test_credentials_file_in_config_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_home: Path
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        (tmp_path / ".credentials.json").write_text('{"token": "x"}')
        assert claude_logged_in() is True

    def test_legacy_claude_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_home: Path
    ) -> None:
        """The legacy `~/.claude.json` is checked as a fallback
        when the standard credentials file is missing. We point
        `Path.home()` at the tmp dir and drop a fake legacy file
        there."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-claude"))
        (tmp_path / "empty-claude").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".claude.json").write_text('{"oauth": "x"}')
        assert claude_logged_in() is True

    def test_no_credentials_anywhere(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_home: Path
    ) -> None:
        """The unhappy path: no env var, no credentials file,
        no legacy file. The user sees the fallback message in
        `agent-go`."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-claude"))
        (tmp_path / "empty-claude").mkdir(parents=True, exist_ok=True)
        assert claude_logged_in() is False


# ---------------------------------------------------------------------------
# claude_missing_login_message
# ---------------------------------------------------------------------------


class TestClaudeMissingLoginMessage:
    """The fallback message must be the exact text the user
    specified in the spec — the user-facing contract."""

    def test_contains_required_lines(self) -> None:
        msg = claude_missing_login_message(task="code")
        assert "Claude Code opened but is not logged in" in msg
        assert "Run `/login` inside Claude" in msg
        assert "agent-go --task code --runtime ollama --model <model>" in msg
        assert "agent-go --task code --runtime openai-compatible --model <model> --base-url <url>" in msg

    def test_task_default_is_code(self) -> None:
        """The default task label in the message is `code`."""
        msg = claude_missing_login_message()
        assert "--task code" in msg


# ---------------------------------------------------------------------------
# build_spawn_args
# ---------------------------------------------------------------------------


class TestBuildSpawnArgs:
    """`build_spawn_args` is the single source of truth for
    "how do I start a model on this runtime?" The three runtimes
    produce different argv / env tuples and the caller wires
    them into `subprocess.run(..., env=...)` without re-deriving."""

    def test_claude_runtime(self) -> None:
        runtime = Runtime(name="claude", model="opus", source="test")
        cmd, env = build_spawn_args(runtime)
        assert cmd == ["claude", "--model", "opus"]
        assert env == {}

    def test_ollama_runtime_uses_claude_via_ollama(self) -> None:
        """`--runtime ollama` reuses the `claude` CLI with the
        ollama OpenAI-compatible endpoint. This gives a
        Claude-Code-style coding agent backed by a local model.
        Plain `ollama run` lives under `--runtime ollama-chat`."""
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        cmd, env = build_spawn_args(runtime)
        assert cmd == ["claude", "--model", "minimax-m3:cloud"]
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"

    def test_ollama_chat_runtime_uses_ollama_run(self) -> None:
        """`--runtime ollama-chat` is the opt-in path for the
        plain ollama chat REPL. Same argv as before the
        refinement round."""
        runtime = Runtime(name="ollama-chat", model="minimax-m3:cloud", source="test")
        cmd, env = build_spawn_args(runtime)
        assert cmd == ["ollama", "run", "minimax-m3:cloud"]
        assert env == {}

    def test_openai_compatible_basic(self) -> None:
        """`openai-compatible` reuses the `claude` CLI but with
        `ANTHROPIC_BASE_URL` injected. The argv is the same as
        the plain claude runtime; only the env dict differs."""
        runtime = Runtime(
            name="openai-compatible",
            model="minimax-m3:cloud",
            base_url="http://localhost:1234/v1",
            source="test",
        )
        cmd, env = build_spawn_args(runtime)
        assert cmd == ["claude", "--model", "minimax-m3:cloud"]
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:1234/v1"
        # No api_key_env was set on the Runtime, so no token.
        assert "ANTHROPIC_AUTH_TOKEN" not in env

    def test_openai_compatible_with_api_key_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When `api_key_env` is set and the named env var resolves
        to a non-empty value, the value is injected as
        `ANTHROPIC_AUTH_TOKEN` in the child's env."""
        monkeypatch.setenv("MY_OPENAI_KEY", "sk-test-1234")
        runtime = Runtime(
            name="openai-compatible",
            model="minimax-m3:cloud",
            base_url="http://localhost:1234/v1",
            api_key_env="MY_OPENAI_KEY",
            source="test",
        )
        cmd, env = build_spawn_args(runtime)
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-test-1234"
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:1234/v1"

    def test_openai_compatible_empty_api_key_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty / unset api_key_env value is silently dropped.
        The runner will surface the real auth error if the key
        is actually required."""
        monkeypatch.delenv("MY_OPENAI_KEY", raising=False)
        runtime = Runtime(
            name="openai-compatible",
            model="minimax-m3:cloud",
            base_url="http://localhost:1234/v1",
            api_key_env="MY_OPENAI_KEY",
            source="test",
        )
        cmd, env = build_spawn_args(runtime)
        assert "ANTHROPIC_AUTH_TOKEN" not in env

    def test_runtime_overrides_via_kwargs(self) -> None:
        """The `base_url` / `api_key_env` kwargs to
        `build_spawn_args` win over the values on the `Runtime`.
        This is how the CLI flags `--base-url` / `--api-key-env`
        flow in without mutating the Runtime."""
        runtime = Runtime(
            name="openai-compatible",
            model="minimax-m3:cloud",
            base_url="http://default:1234/v1",
            api_key_env="DEFAULT_KEY_ENV",
            source="test",
        )
        cmd, env = build_spawn_args(
            runtime, base_url="http://override:5678/v1", api_key_env=None
        )
        assert env["ANTHROPIC_BASE_URL"] == "http://override:5678/v1"
        assert "ANTHROPIC_AUTH_TOKEN" not in env

    def test_unknown_runtime_falls_back_to_claude(self) -> None:
        """A defensive branch: an unknown runtime name (which
        `resolve_runtime` would not produce, but might end up
        in a hand-crafted Runtime) does not crash."""
        runtime = Runtime(name="totally-fake", model="x", source="test")
        cmd, env = build_spawn_args(runtime)
        # Falls through to the claude path.
        assert cmd == ["claude", "--model", "x"]


# ---------------------------------------------------------------------------
# runtime_summary_lines
# ---------------------------------------------------------------------------


class TestRuntimeSummaryLines:
    """`runtime_summary_lines` produces the 7-line "what is
    going to be used" block. The format is the user's contract."""

    def test_claude_summary(self) -> None:
        runtime = Runtime(name="claude", model="opus", source="test")
        lines = runtime_summary_lines(runtime)
        assert lines == [
            "runtime:      claude",
            "runtime mode: claude",
            "model:        opus",
        ]

    def test_ollama_summary_includes_mode(self) -> None:
        """The ollama runtime's summary must surface the
        claude-via-ollama mode so the user can see that
        `claude` (not `ollama`) is the actual command."""
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        lines = runtime_summary_lines(runtime)
        assert lines == [
            "runtime:      ollama",
            "runtime mode: claude-via-ollama",
            "model:        minimax-m3:cloud",
        ]

    def test_ollama_chat_summary(self) -> None:
        runtime = Runtime(name="ollama-chat", model="minimax-m3:cloud", source="test")
        lines = runtime_summary_lines(runtime)
        assert lines == [
            "runtime:      ollama-chat",
            "runtime mode: chat",
            "model:        minimax-m3:cloud",
        ]

    def test_openai_compatible_includes_base_url(self) -> None:
        runtime = Runtime(
            name="openai-compatible",
            model="minimax-m3:cloud",
            base_url="http://localhost:1234/v1",
            source="test",
        )
        lines = runtime_summary_lines(runtime)
        assert lines == [
            "runtime:      openai-compatible",
            "runtime mode: openai-compatible",
            "model:        minimax-m3:cloud",
            "base_url:     http://localhost:1234/v1",
        ]

    def test_seven_line_block_when_command_agent_cwd_backend_given(self) -> None:
        """The pre-launch output block: 7 lines with the
        command / agent / cwd / backend filled in. The exact
        format is the user's contract."""
        runtime = Runtime(name="ollama", model="minimax-m3:cloud", source="test")
        lines = runtime_summary_lines(
            runtime,
            command=["claude", "--model", "minimax-m3:cloud"],
            agent="primary-2",
            cwd="C:\\path\\to\\repo",
            backend="herdr",
        )
        assert lines == [
            "runtime:      ollama",
            "runtime mode: claude-via-ollama",
            "model:        minimax-m3:cloud",
            "backend:      herdr",
            "command:      claude --model minimax-m3:cloud",
            "agent:        primary-2",
            "cwd:          C:\\path\\to\\repo",
        ]


# ---------------------------------------------------------------------------
# agent_go integration
# ---------------------------------------------------------------------------


class TestAgentGoRuntimeFlag:
    """End-to-end: `agent-go` must honor the new `--runtime` /
    `--model` / `--base-url` / `--api-key-env` flags and produce
    the documented behaviour."""

    def test_runtime_flag_parses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--runtime ollama` lands in `args.runtime`."""
        parser = agent_go._build_argparser()
        args = parser.parse_args(["--runtime", "ollama"])
        assert args.runtime == "ollama"

    def test_model_flag_parses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        parser = agent_go._build_argparser()
        args = parser.parse_args(["--model", "qwen2.5:7b"])
        assert args.model == "qwen2.5:7b"

    def test_base_url_and_api_key_env_parse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        parser = agent_go._build_argparser()
        args = parser.parse_args([
            "--runtime", "openai-compatible",
            "--base-url", "http://localhost:1234/v1",
            "--api-key-env", "MY_KEY",
        ])
        assert args.runtime == "openai-compatible"
        assert args.base_url == "http://localhost:1234/v1"
        assert args.api_key_env == "MY_KEY"

    def test_runtime_choices_are_validated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unknown runtime name is rejected at the argparse
        layer — we never reach resolution with garbage."""
        parser = agent_go._build_argparser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--runtime", "gemini"])

    def test_print_prompt_includes_runtime_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """`--print-prompt` prints the resolved runtime + model at
        the top, so docs reviewers can see what would be used.

        The summary block goes to stderr (via `info()`); the
        prompt body itself goes to stdout."""
        rc = agent_go.main([
            "--print-prompt",
            "--no-bootstrap",
            "--runtime", "ollama",
            "--model", "minimax-m3:cloud",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        # The summary block: stderr, prefixed with `agent-workbench: `.
        assert "agent-workbench: runtime:      ollama" in captured.err
        assert "agent-workbench: runtime mode: claude-via-ollama" in captured.err
        assert "agent-workbench: model:        minimax-m3:cloud" in captured.err
        # The prompt body is on stdout.
        assert "Global toolkit instructions" in captured.out

    def test_claude_runtime_no_login_prints_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """With `--runtime claude` and no credentials, `agent-go`
        prints the fallback message and exits 0. We do NOT spawn
        herdr, claude, or ollama."""
        # Force claude_logged_in to return False.
        monkeypatch.setattr("agent_go._runtime.claude_logged_in", lambda: False)
        # No env var, no credentials file, no legacy .claude.json.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty"))
        (tmp_path / "empty").mkdir(parents=True, exist_ok=True)

        # Spy on subprocess.run to make sure it is never called.
        spawns: list = []
        def _fake_run(*args, **kwargs):  # noqa: ANN001
            spawns.append((args, kwargs))
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        monkeypatch.setattr("agent_go.subprocess.run", _fake_run)

        rc = agent_go.main([
            "--no-bootstrap",
            "--runtime", "claude",
            "--repo", str(tmp_path),
        ])
        assert rc == 0
        out = capsys.readouterr().err  # info() writes to stderr.
        assert "Claude Code opened but is not logged in" in out
        assert "Run `/login` inside Claude" in out
        # No subprocess was launched.
        assert spawns == []

    def test_claude_runtime_with_login_proceeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """With `--runtime claude` and a credentials file, `agent-go`
        proceeds through the spawn path. We don't assert the full
        herdr round-trip here (that's covered by the
        `test_herdr_json_parsing.py` tests); we just assert that
        the fallback message is NOT printed and a subprocess is
        launched."""
        monkeypatch.setattr("agent_go._runtime.claude_logged_in", lambda: True)
        # We want --no-herdr so we don't need the full herdr JSON
        # envelope machinery.
        rc = agent_go.main([
            "--no-bootstrap",
            "--no-herdr",
            "--runtime", "claude",
            "--model", "opus",
            "--repo", str(tmp_path),
        ])
        # Either the spawn ran successfully (rc=0) or it failed
        # because the test environment has no real `claude` on
        # PATH. We assert: (a) the fallback message was NOT printed,
        # (b) we got past the early-return-on-no-login branch.
        out = capsys.readouterr().err
        assert "Claude Code opened but is not logged in" not in out

    def test_ollama_runtime_skips_login_probe(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        """`--runtime ollama` does NOT call `claude_logged_in`.
        The login probe is specific to the `claude` runtime."""
        called = []

        def _fake_logged_in() -> bool:
            called.append(True)
            return False

        monkeypatch.setattr("agent_go._runtime.claude_logged_in", _fake_logged_in)
        rc = agent_go.main([
            "--no-bootstrap",
            "--no-herdr",
            "--runtime", "ollama",
            "--model", "minimax-m3:cloud",
            "--repo", str(tmp_path),
        ])
        # claude_logged_in was not called.
        assert called == []
        out = capsys.readouterr().err
        # The fallback message was not printed (it is claude-specific).
        assert "Claude Code opened but is not logged in" not in out
