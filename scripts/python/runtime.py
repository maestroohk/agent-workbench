"""Runtime / provider selection for agent-workbench.

The workbench was originally written with `claude` as the only
interactive model runner. Users without Anthropic access had no
documented path to a working session. This module introduces four
first-class runtimes:

  - `claude`            — the Anthropic Claude Code CLI (default).
  - `ollama`            — Claude Code pointed at a local ollama
    (`ANTHROPIC_BASE_URL=http://localhost:11434`). Gives the same
    Claude-Code-style coding-agent experience, but with a local model.
    This is the right runtime for `agent-go --task code` on a machine
    without Anthropic access. (Previously, `--runtime ollama` invoked
    `ollama run <model>` which gave a `>>> Send a message` chat REPL —
    not what a coding workflow needs.)
  - `ollama-chat`       — the plain ollama chat REPL (`ollama run`).
    Opt-in for users who explicitly want a chat-style session.
  - `openai-compatible` — Claude Code pointed at a custom
    `ANTHROPIC_BASE_URL`, used for LM Studio, vLLM, LiteLLM, and
    any other provider that speaks the Anthropic wire protocol
    through that env var.

Selection order is `CLI > env > config > default` for both the
runtime name and the model name. The CLI flags live on `agent-go`
(`--runtime`, `--model`, `--base-url`, `--api-key-env`); the
config file lives at `~/.agent-workbench/config.toml` with sections
(`[runtime]`, `[claude]`, `[ollama]`, `[ollama_chat]`,
`[openai_compatible]`, plus `[backend]` and `[ui]` for the
optional setup flow); the env vars are `AGENT_RUNTIME` and
`AGENT_MODEL`.

`build_spawn_args(runtime, model, *, base_url, api_key_env)` is
the single source of truth for "how do I start the model on this
runtime?". It returns `(cmd, env_overrides)` so callers can wire
the result into `subprocess.run(..., env=...)` without each
command re-deriving the argv.

`claude_logged_in()` probes for credentials (env vars, the standard
credentials file, the legacy `~/.claude.json`) so `agent-go` can
print a clear fallback message instead of dropping the user into
a broken Claude pane that says "Not logged in · Run /login".

The module deliberately avoids `tomli` / `tomllib` for the
config parser. The config schema is small and flat; a 30-line
line-based parser is enough and saves a dependency on older
Python versions. (Newer Python can swap in `tomllib` later if the
schema grows.)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# --- The runtime universe ------------------------------------------------

RUNTIMES: tuple[str, ...] = (
    "claude",
    "ollama",
    "ollama-chat",
    "openai-compatible",
)

# `claude` is the default for backwards compatibility with users
# who already have Anthropic access. New users without a Claude
# subscription set `[runtime] default = "ollama"` in their config
# or use `--runtime ollama` on the command line.
DEFAULT_RUNTIME: str = "claude"

# Each runtime has its own sensible default model. `minimax-m3:cloud`
# is no longer hard-coded as a Claude model — it is the default
# for `ollama`, `ollama-chat`, and `openai-compatible`. Claude's
# default is the Anthropic-recommended `opus` (Claude Code resolves
# the alias).
DEFAULT_MODELS: dict[str, str] = {
    "claude": "opus",
    "ollama": "minimax-m3:cloud",
    "ollama-chat": "minimax-m3:cloud",
    "openai-compatible": "minimax-m3:cloud",
}

# Filename of the workbench config file. The same path is used by
# `agent_claude.resolve_model`, which reads the legacy single-line
# `model = "..."` form. The new `load_config` here understands
# both the legacy form and the section-based schema.
CONFIG_FILENAME = "config.toml"
CONFIG_PATH = Path.home() / ".agent-workbench" / CONFIG_FILENAME


@dataclass(frozen=True)
class Runtime:
    """A resolved runtime + model + endpoint configuration.

    `name` is one of `RUNTIMES`. `model` is the model identifier
    passed to the runner (e.g. "opus" for claude, "minimax-m3:cloud"
    for ollama). `base_url` and `api_key_env` are populated for the
    `openai-compatible` runtime; for the others they are `None`.
    `source` records which layer of the resolution order supplied
    the name (`cli` / `env` / `config` / `default`) so the caller
    can show a "what was used and why" line.

    `mode` is a free-form label that callers can set to record
    *how* the runtime is being used. For the `ollama` runtime it
    is `"claude-via-ollama"` (default) or `"chat"`. For other
    runtimes it is `"default"`. The pre-launch output block reads
    this field to print the `runtime mode:` line.
    """

    name: str
    model: str
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    source: str = "default"
    mode: str = "default"

    def is_claude(self) -> bool:
        return self.name == "claude"

    def is_ollama(self) -> bool:
        return self.name == "ollama"

    def is_ollama_chat(self) -> bool:
        return self.name == "ollama-chat"

    def is_openai_compatible(self) -> bool:
        return self.name == "openai-compatible"


# --- Config parsing ------------------------------------------------------

# A minimal line-based parser for the four-line config we read.
# We do not need a full TOML parser: the schema is one level of
# section headers, `key = value` pairs, comments starting with
# `#`, and quoted values. Anything more complex is overkill.

# Section header: `[name]` (allows underscores and dots).
_SECTION_RE = re.compile(r"^\s*\[(?P<name>[A-Za-z0-9_.\-]+)\]\s*$")

# `key = value`. The value can be a bare token or a quoted string.
_KV_RE = re.compile(r"""^\s*(?P<key>[A-Za-z0-9_\-]+)\s*=\s*(?P<value>"[^"]*"|'[^']*'|[^#\s][^#]*?)\s*(?:#.*)?$""")


def _strip_quotes(value: str) -> str:
    """Remove surrounding single or double quotes if present."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_config(path: Optional[Path] = None) -> dict:
    """Return the parsed config as `{section_name: {key: value}}`.

    Top-level (no section) `key = value` lines land in a special
    section called `"_"` so callers can detect the legacy
    `model = "..."` form. Returns an empty dict on missing or
    unparseable files; this is a best-effort loader and a corrupt
    config must not crash `agent-go`.

    Sections with the same name as a runtime (`claude`, `ollama`,
    `openai_compatible`) are normalised: `openai_compatible` in
    the file becomes `openai-compatible` in the returned dict
    (the file form uses an underscore; the runtime name uses a
    hyphen to match the CLI flag).
    """
    p = Path(path) if path else CONFIG_PATH
    if not p.is_file():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    return _parse_config_text(text)


def _parse_config_text(text: str) -> dict:
    """Pure-function config parser. `load_config` wraps it with
    file I/O so the tests can call this directly."""
    result: dict[str, dict] = {}
    current = "_"
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0]  # strip trailing comments
        if not line.strip():
            continue
        section_match = _SECTION_RE.match(line)
        if section_match:
            name = section_match.group("name").strip()
            # Normalise "openai_compatible" -> "openai-compatible" so the
            # section key matches the runtime name used elsewhere.
            if name == "openai_compatible":
                name = "openai-compatible"
            current = name
            result.setdefault(current, {})
            continue
        kv_match = _KV_RE.match(line)
        if kv_match:
            key = kv_match.group("key").strip()
            value = _strip_quotes(kv_match.group("value"))
            result.setdefault(current, {})[key] = value
            continue
        # Unrecognised lines are ignored — the file is a best-effort
        # source of defaults, not a hard contract.
    return result


# --- Runtime resolution --------------------------------------------------


def resolve_runtime(
    *,
    cli_value: Optional[str],
    env_value: Optional[str],
    config: dict,
    default: str = DEFAULT_RUNTIME,
) -> tuple[str, str]:
    """Return `(runtime_name, source)` per the resolution order.

    Order: CLI > env > config (`[runtime] default`) > `default`.
    `None` in any layer falls through to the next. Unknown values
    (e.g. `cli_value="gemini"`) are treated as if `None` — the
    config and default layers still get a chance.
    """
    if cli_value and cli_value in RUNTIMES:
        return cli_value, "cli"
    if env_value and env_value in RUNTIMES:
        return env_value, "env"
    cfg_default = (config.get("runtime") or {}).get("default")
    if cfg_default and cfg_default in RUNTIMES:
        return cfg_default, "config"
    if default in RUNTIMES:
        return default, "default"
    # Fallback path: `default` was set to something exotic. Return
    # the canonical `DEFAULT_RUNTIME` instead.
    return DEFAULT_RUNTIME, "default"


def resolve_model(
    runtime_name: str,
    *,
    cli_model: Optional[str],
    env_model: Optional[str],
    config: dict,
) -> tuple[str, str]:
    """Return `(model, source)` for the given runtime.

    Order: CLI > env > config (`[<runtime>] model`, with the
    legacy top-level `model` key as a fallback) > `DEFAULT_MODELS[runtime]`.
    """
    if cli_model:
        return cli_model, "cli"
    if env_model:
        return env_model, "env"
    # Per-runtime config section: [claude] / [ollama] / [ollama_chat]
    # / [openai-compatible]. The runtime name uses a hyphen
    # (`openai-compatible`), but some sections use an underscore
    # (`ollama_chat` matches the runtime `ollama-chat`). Look up
    # both forms so the user's `[ollama_chat] model = "..."` lands
    # in the right place.
    section = config.get(runtime_name) or config.get(runtime_name.replace("-", "_")) or {}
    cfg_model = section.get("model")
    if cfg_model:
        return cfg_model, "config"
    # Legacy top-level `model = "..."` form. We honour it only if
    # the runtime matches (or is unset, i.e. the user is on the
    # default runtime).
    legacy = config.get("_") or {}
    legacy_model = legacy.get("model")
    if legacy_model:
        return legacy_model, "config"
    return DEFAULT_MODELS.get(runtime_name, DEFAULT_MODELS["claude"]), "default"


def resolve_ollama_mode(config: dict) -> str:
    """Return the resolved `[ollama] mode` for the ollama runtime.

    The `ollama` runtime can run in two modes:
      - `"claude"` (default) — Claude-Code-via-ollama. Reuses the
        installed `claude` CLI with `ANTHROPIC_BASE_URL` pointed
        at ollama's OpenAI-compatible HTTP endpoint. This is the
        right mode for coding workflows.
      - `"chat"` — plain ollama chat REPL (`ollama run <model>`).
        Opt-in for users who explicitly want a chat-style session.

    The user controls the mode via the `[ollama] mode` config key
    (default `"claude"`). The `AGENT_OLLAMA_MODE` env var wins
    over the config.

    Returns the mode as a string. Unknown values fall back to
    `"claude"`.
    """
    env_mode = os.environ.get("AGENT_OLLAMA_MODE", "").strip().lower()
    if env_mode in ("claude", "chat"):
        return env_mode
    cfg_mode = ((config.get("ollama") or {}).get("mode") or "").strip().lower()
    if cfg_mode in ("claude", "chat"):
        return cfg_mode
    return "claude"


# --- Login detection -----------------------------------------------------

# The Claude Code CLI stores credentials in
# `~/.claude/.credentials.json` on Windows and Linux (Keychain on
# macOS, but the file is also written as a cache). The legacy
# location is `~/.claude.json`. We probe both.

_CREDENTIAL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


def claude_logged_in() -> bool:
    """True if Claude Code is likely authenticated.

    Returns True if any of:
      - `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or
        `CLAUDE_CODE_OAUTH_TOKEN` is set in the environment.
      - `$CLAUDE_CONFIG_DIR/.credentials.json` exists and is
        non-empty (the standard Claude Code credentials file).
      - `~/.claude/.credentials.json` exists (default location
        when `CLAUDE_CONFIG_DIR` is unset).
      - `~/.claude.json` exists (legacy pre-`CLAUDE_CONFIG_DIR` location).

    This is a probe, not a validation. A present-but-expired token
    still reports True; the user will see the actual auth error
    inside the Claude pane. The point is to catch the obvious
    "no credentials anywhere" case before we drop the user into
    a broken pane.
    """
    for var in _CREDENTIAL_ENV_VARS:
        if os.environ.get(var, "").strip():
            return True
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    if (config_dir / ".credentials.json").is_file():
        return True
    if (Path.home() / ".claude.json").is_file():
        return True
    return False


def claude_missing_login_message(task: str = "code") -> str:
    """Return the fallback message printed when Claude is not logged in.

    The message is the same one the user sees in the herdr pane
    when Claude boots without credentials. We print it up-front
    in `agent-go` so the user can pivot to ollama or an
    openai-compatible endpoint before launching herdr.
    """
    return (
        "Claude Code opened but is not logged in.\n"
        "Run `/login` inside Claude, or use:\n"
        f"  agent-go --task {task} --runtime ollama --model <model>\n"
        f"  agent-go --task {task} --runtime openai-compatible --model <model> --base-url <url>\n"
    )


# --- Spawn-args construction ---------------------------------------------

# The openai-compatible runtime needs the API key value at spawn
# time, not at parse time (the user may set the env var in a
# separate command between `agent-go` resolution and the actual
# subprocess.run). `build_spawn_args` therefore takes the env
# var *name* and reads the value via `os.environ` lazily.


def build_spawn_args(
    runtime: Runtime,
    *,
    base_url: Optional[str] = None,
    api_key_env: Optional[str] = None,
) -> tuple[list[str], dict[str, str]]:
    """Return `(cmd, env_overrides)` for spawning the model on `runtime`.

    `cmd` is the argv list (already passed through `resolve_executable`
    in the caller so Windows `.cmd` shims work). `env_overrides` is
    the dict to merge into the child process's environment.

    The four runtimes map to four argv/env tuples:

      - `claude`            — `["claude", "--model", m]`, `{}`.
      - `ollama`            — `["claude", "--model", m]` with
        `ANTHROPIC_BASE_URL=http://localhost:11434` and
        `ANTHROPIC_AUTH_TOKEN=ollama`. ollama serves
        OpenAI-compatible HTTP at /v1 and accepts any non-empty
        token, so the same `claude` CLI works against a local
        ollama model. This is the "claude-via-ollama" flow.
      - `ollama-chat`       — `["ollama", "run", m]`, `{}`. Plain
        ollama chat REPL. Opt-in only.
      - `openai-compatible` — `["claude", "--model", m]` with the
        user-supplied `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`
        (read at spawn time from `api_key_env`).

    `base_url` and `api_key_env` arguments to this function override
    whatever is on the `Runtime`. This is how the CLI flags
    `--base-url` / `--api-key-env` flow in.
    """
    if runtime.is_claude():
        return _build_claude_args(runtime.model)
    if runtime.is_ollama():
        return _build_ollama_claude_args(runtime.model)
    if runtime.is_ollama_chat():
        return _build_ollama_chat_args(runtime.model)
    if runtime.is_openai_compatible():
        return _build_openai_compatible_args(
            runtime.model,
            base_url=base_url or runtime.base_url,
            api_key_env=api_key_env or runtime.api_key_env,
        )
    # Unknown runtime — fall back to claude; the caller logged
    # the issue already. This branch is defensive.
    return _build_claude_args(runtime.model)


def _build_claude_args(model: str) -> tuple[list[str], dict[str, str]]:
    return ["claude", "--model", model], {}


def _build_ollama_claude_args(model: str) -> tuple[list[str], dict[str, str]]:
    """Claude-Code-via-ollama: reuse the installed `claude` CLI
    but point it at ollama's OpenAI-compatible HTTP endpoint.

    ollama listens on `http://localhost:11434` by default and
    serves OpenAI-compatible HTTP at `/v1`. It does not validate
    the `Authorization: Bearer` token, so we set a fixed
    non-empty placeholder (`"ollama"`). The user keeps the
    full Claude Code agentic experience, just pointed at their
    own local model. The same argv as the `claude` runtime is
    returned; only the env dict differs.
    """
    cmd = ["claude", "--model", model]
    env = {
        "ANTHROPIC_BASE_URL": "http://localhost:11434",
        "ANTHROPIC_AUTH_TOKEN": "ollama",
    }
    return cmd, env


def _build_ollama_chat_args(model: str) -> tuple[list[str], dict[str, str]]:
    """Plain ollama chat REPL: `ollama run <model>`.

    Opt-in only. The default `ollama` runtime uses the
    claude-via-ollama flow above. Users who explicitly want the
    `>>> Send a message` REPL use `--runtime ollama-chat` (or
    set `[runtime] default = "ollama-chat"` in their config).
    """
    return ["ollama", "run", model], {}


def _build_openai_compatible_args(
    model: str,
    *,
    base_url: Optional[str],
    api_key_env: Optional[str],
) -> tuple[list[str], dict[str, str]]:
    """Build the argv + env for the openai-compatible runtime.

    We reuse the `claude` CLI: it honours `ANTHROPIC_BASE_URL` and
    `ANTHROPIC_AUTH_TOKEN` for any provider that speaks the
    Anthropic wire protocol at that base URL. The same argv as
    the plain claude runtime is returned; only the env dict
    differs.
    """
    cmd = ["claude", "--model", model]
    env: dict[str, str] = {}
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    if api_key_env:
        value = os.environ.get(api_key_env, "").strip()
        if value:
            env["ANTHROPIC_AUTH_TOKEN"] = value
        # An empty / unset value is not an error here — the user
        # may be running in an environment where the key is
        # injected another way (apiKeyHelper, gateway session).
        # The runner will surface the actual auth error.
    return cmd, env


# --- Public helpers used by the commands --------------------------------


def _runtime_mode_label(runtime: Runtime) -> str:
    """Return the human-readable label for the runtime's `mode` field.

    The pre-launch output block uses this for the `runtime mode:` line.

    The mapping:
      - `ollama` with mode `"claude"` (default)  -> "claude-via-ollama"
      - `ollama` with mode `"chat"`              -> "chat"
      - `ollama-chat` runtime                    -> "chat"
      - everything else                          -> runtime.name

    The `"claude-via-ollama"` label is intentional: the actual
    command is `claude --model <m>`, not `ollama run`, so the
    user-facing summary should not just say "claude" (which
    would be misleading) nor just "ollama" (which hides that
    Claude Code is the runner). The full label makes the
    shape of the flow obvious at a glance.
    """
    if runtime.is_ollama():
        if runtime.mode == "chat":
            return "chat"
        return "claude-via-ollama"
    if runtime.is_ollama_chat():
        return "chat"
    return runtime.name


def runtime_summary_lines(
    runtime: Runtime,
    *,
    command: Optional[list[str]] = None,
    agent: Optional[str] = None,
    cwd: Optional[str] = None,
    backend: Optional[str] = None,
) -> list[str]:
    """Return the 7-line "what is being used" block as a list of strings.

    Each line is the body of an `info()` call (the caller adds the
    `agent-workbench: ` prefix).

    The first two lines are always present:
        runtime:      <name>
        runtime mode: <mode label>

    Then optional lines as `command` / `agent` / `cwd` / `backend`
    are provided:
        model:        <model>
        backend:      <backend>     (only if backend is given)
        command:      <argv>        (only if command is given)
        agent:        <name>        (only if agent is given)
        cwd:          <path>        (only if cwd is given)

    Format matches the user's spec for the refinement round.
    """
    lines = [
        f"runtime:      {runtime.name}",
        f"runtime mode: {_runtime_mode_label(runtime)}",
        f"model:        {runtime.model}",
    ]
    if runtime.base_url:
        lines.append(f"base_url:     {runtime.base_url}")
    if backend is not None:
        lines.append(f"backend:      {backend}")
    if command is not None:
        lines.append(f"command:      {' '.join(command)}")
    if agent is not None:
        lines.append(f"agent:        {agent}")
    if cwd is not None:
        lines.append(f"cwd:          {cwd}")
    return lines
