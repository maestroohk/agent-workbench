"""`agent-go` — the one-liner that takes you from a clean machine to a
working agent session.

What it does, in order:

1. Probes every dependency the workbench orchestrates. If any of
   `claude`, `herdr`, `firstmate`, `no-mistakes`, `treehouse`, `gnhf`,
   `ollama`, or `wezterm` are missing, runs `bootstrap.install_dependencies`
   to fetch the ones the user asked for (default: the full set).
2. Ensures `~/.local/bin` is on PATH for the current process (so the
   shim for `herdr` / `claude` we just installed is reachable).
3. Assembles the system prompt via `build_prompt.assemble_prompt` and
   writes it to `<repo>/.agent/SYSTEM_PROMPT.md` (where Claude Code
   auto-loads it as `CLAUDE.md`).
4. Starts the herdr server in the background, if herdr is present and
   the server is not already running.
5. Launches the model:
   - `claude` CLI if available (prefers herdr-isolated agent);
   - else `ollama run <model>`;
   - else prints a paste-ready prompt and exits 0.

The point is that a single `agent-go` (or `agent-go --print-cmd` to
emit the one-liner) on a fresh machine ends with the user inside a
herdr pane running Claude Code with the global rules pre-applied.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from build_prompt import assemble_prompt
from scan_repo import AGENT_DIR_NAME
from utils import (
    AGENT_BIN_DIR,
    DEFAULT_MODEL,
    find_repo_root,
    first_executable,
    info,
    is_agent_name_taken_error,
    parse_json_loose,
    resolve_executable,
    run_command,
    unique_agent_name,
    workbench_root,
    write_text,
)

import bootstrap as _bootstrap
import runtime as _runtime


# --- herdr JSON helpers --------------------------------------------------
# herdr emits JSON envelopes like:
#   {"worktree_created":{"worktree":{"path":"C:\\...\\worktree-x",...},...}}
#   {"agent_started":{"agent":"primary","cwd":"C:\\...","argv":[...]}}
# The previous code passed the raw stdout as `--cwd`, which sent the
# whole JSON blob to herdr and made the agent land in $HOME. These
# helpers extract the fields the workbench actually needs.

def _extract_worktree_path(payload: Optional[dict]) -> Optional[str]:
    """Return the worktree path from a `worktree_created` envelope, or None.

    Tolerant of two shapes:
      1. {"worktree_created":{"worktree":{"path":"..."}}}  -- current herdr
      2. {"path":"..."}                                     -- future-proof
    """
    if not payload:
        return None
    inner = payload.get("worktree_created") if isinstance(payload.get("worktree_created"), dict) else payload
    wt = inner.get("worktree") if isinstance(inner, dict) else None
    if isinstance(wt, dict):
        path = wt.get("path")
        if path:
            return str(path)
    if isinstance(inner, dict):
        path = inner.get("path")
        if path:
            return str(path)
    return None


def _extract_agent_info(payload: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """Return (cwd, agent_name) from an `agent_started` envelope, or (None, None).

    Tolerant of:
      1. {"agent_started":{"agent":"primary","cwd":"...","argv":[...]}}
      2. {"agent":"primary","cwd":"...","argv":[...]}            -- top-level
    """
    if not payload:
        return None, None
    inner = payload.get("agent_started") if isinstance(payload.get("agent_started"), dict) else payload
    if not isinstance(inner, dict):
        return None, None
    cwd = inner.get("cwd")
    name = inner.get("agent") or inner.get("name")
    return (str(cwd) if cwd else None), (str(name) if name else None)


def _paths_differ(a: str, b: str) -> bool:
    """True if two filesystem paths are not the same after normalisation.

    `os.path.normcase` makes the comparison case-insensitive on Windows
    and applies the platform path-separator normalisation, so a Windows
    path with backslashes matches the same path with forward slashes.
    """
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) != os.path.normcase(os.path.normpath(b))


def _print_attach_instructions(*, repo: Path, worktree: str, actual_cwd: str, agent_name: str) -> None:
    """Print the next-step block to stderr after a successful `herdr agent start`.

    The block tells the user where the agent is, what to attach with,
    and where to paste the task prompt. Without this block, the user is
    dropped at the PowerShell prompt with no clear next action.
    """
    info(f"herdr agent '{agent_name}' started")
    info(f"  repo root   : {repo}")
    info(f"  worktree    : {worktree}")
    info(f"  agent cwd   : {actual_cwd}")
    info(f"  agent name  : {agent_name}")
    info(f"  attach with : herdr agent attach {agent_name}")
    info("NEXT STEP: paste the task prompt in the herdr pane (or in the attach session).")


def _should_auto_attach() -> bool:
    """Return True if `agent-go` should auto-attach the user's terminal.

    Auto-attach is skipped when:
    - the env var `AGENT_GO_NO_AUTO_ATTACH` is set to a truthy value.
    - stdout is not a TTY (CI, redirected, captured by a parent process).
    """
    if os.environ.get("AGENT_GO_NO_AUTO_ATTACH", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _auto_attach(herdr: str, agent_name: str) -> int:
    """Run `herdr agent attach <name>` as a blocking foreground call.

    `herdr agent attach` takes over the user's terminal and drops them
    into the agent's pane. We do this as a blocking call (no
    `capture_output`) so the attach session uses the user's real TTY.
    If the attach fails for any reason, the agent is still running; the
    instruction block was already printed, so the user has a manual
    fallback.
    """
    info(f"auto-attaching to agent '{agent_name}' (Ctrl-b d to detach, AGENT_GO_NO_AUTO_ATTACH=1 to disable)")
    try:
        result = subprocess.run([herdr, "agent", "attach", agent_name])
    except OSError as exc:
        info(f"herdr agent attach failed to start: {exc}")
        info("the agent is still running; attach manually with: herdr agent attach " + agent_name)
        return 0
    if result.returncode != 0:
        info(
            f"herdr agent attach exited with code {result.returncode}; "
            f"the agent is still running. Attach manually with: "
            f"herdr agent attach {agent_name}"
        )
        return 0
    return result.returncode


# What `agent-go` ensures is installed by default. The user can scope
# with `--bootstrap=claude,herdr` etc.
#
# What is NOT here on purpose:
# - `treehouse` — opt-in via `--bootstrap=treehouse`. A single-agent
#   `agent-go` flow does not need a worktree pool; `agent-fleet` is
#   the path that wants it.
# - `gnhf` — overnight runner, not used by interactive `agent-go`.
#   gnhf ships no Windows release, so leaving it in the default would
#   make every Windows `agent-go` hit the honest-but-noisy
#   'no asset matching' error. Use `agent-overnight` to drive gnhf.
DEFAULT_GO_BOOTSTRAP = (
    "claude",
    "herdr",
    "firstmate",
    "no-mistakes",
    "ollama",
)


def _print_path_hint_if_needed() -> None:
    """If `~/.local/bin` is not on PATH, print the export line for the user."""
    path = os.environ.get("PATH") or ""
    if str(AGENT_BIN_DIR) in path.split(os.pathsep):
        return
    info(f"{AGENT_BIN_DIR} is not on PATH for this shell")
    if os.name == "nt":
        info('add it with: $env:Path = "$env:USERPROFILE\\.local\\bin;$env:Path"')
    else:
        info('add it with: export PATH="$HOME/.local/bin:$PATH"')


def _ensure_path() -> None:
    """Add `~/.local/bin` to PATH for the current process (best-effort)."""
    if str(AGENT_BIN_DIR) not in (os.environ.get("PATH") or "").split(os.pathsep):
        os.environ["PATH"] = str(AGENT_BIN_DIR) + os.pathsep + os.environ.get("PATH", "")


def resolve_backend(*, cli_value: Optional[str], config: dict) -> str:
    """Resolve which orchestrator to use: `herdr` (default),
    `treehouse`, or `none`.

    Order: CLI > `[backend] default` in config > `herdr`. The
    user can also force `none` to skip orchestration entirely.
    Used by the pre-launch output block (the `backend:` line)
    and by callers that need to pick a spawn path.
    """
    if cli_value and cli_value in ("herdr", "treehouse", "none"):
        return cli_value
    cfg_default = (config.get("backend") or {}).get("default", "").strip()
    if cfg_default in ("herdr", "treehouse", "none"):
        return cfg_default
    return "herdr"


def _prompt_user(question: str, *, default: str = "") -> str:
    """Read a line from stdin, with a default. Returns the
    stripped answer (or the default if the user just hit
    enter). We use the built-in `input()` rather than a TUI
    library — this is the workbench's terminal fallback for
    the setup flow.
    """
    if default:
        try:
            response = input(f"{question} [{default}]: ")
        except EOFError:
            return default
    else:
        try:
            response = input(f"{question}: ")
        except EOFError:
            return ""
    response = response.strip()
    return response or default


def _yes_no(question: str, *, default_yes: bool) -> bool:
    """Ask a yes/no question. Returns True for yes, False for no.
    Accepts `y`, `yes`, `n`, `no` (case-insensitive). Empty
    input returns the default."""
    default = "Y" if default_yes else "N"
    response = _prompt_user(question, default=default).lower()
    if not response:
        return default_yes
    if response in ("y", "yes"):
        return True
    if response in ("n", "no"):
        return False
    return default_yes


def _run_setup_interactive(config_path: Path) -> int:
    """Interactively write `~/.agent-workbench/config.toml`.

    The flow:

    1. Probe for `lavish-axi`. If present and `[ui] setup =
       "lavish-axi"`, defer to it as a black box (the user
       saves the config in the browser; we read it back from
       `config_path` after lavish-axi exits).
    2. Otherwise, walk the user through four terminal
       prompts: default runtime, model for that runtime,
       backend default (`herdr` / `treehouse` / `none`),
       UI default (`terminal` / `lavish-axi`).
    3. Write the answers to `config_path` (with a clear
       comment header so the file is self-documenting).
       If the file already exists, ask before overwriting.

    Returns 0 on success, 1 on user cancel.
    """
    config_path = Path(config_path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text(encoding="utf-8") if config_path.is_file() else None
    if existing:
        info(f"existing config: {config_path}")
        overwrite = _yes_no("overwrite? ", default_yes=False)
        if not overwrite:
            info("setup cancelled; existing config left as-is")
            return 1
    else:
        info(f"will write: {config_path}")
    config = _runtime.load_config(path=config_path)
    lavish_path = resolve_executable("lavish-axi")
    ui_pref = ((config.get("ui") or {}).get("setup") or "").strip().lower()
    lavish_chosen = False
    if lavish_path and (ui_pref == "lavish-axi" or not ui_pref):
        info(f"lavish-axi found at {lavish_path}; deferring to it for the visual setup page")
        if _yes_no("use lavish-axi for setup? ", default_yes=True):
            lavish_chosen = True
    if lavish_chosen:
        # Treat lavish-axi as a black box: spawn it, let the user
        # save the page, and read the resulting config back. We
        # don't try to parse its output; the contract is "the
        # user edited `~/.agent-workbench/config.toml` in the
        # browser, we read it after they save".
        info("opening lavish-axi setup page; save when you are done")
        try:
            result = subprocess.run(
                [lavish_path, "setup", "agent-workbench"],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError:
            info("lavish-axi disappeared mid-setup; falling back to terminal prompts")
            lavish_chosen = False
        except subprocess.TimeoutExpired:
            info("lavish-axi setup timed out after 5 minutes; falling back to terminal prompts")
            lavish_chosen = False
        else:
            if result.returncode != 0:
                info(f"lavish-axi setup exited {result.returncode}; falling back to terminal prompts")
                lavish_chosen = False
            else:
                info("lavish-axi setup completed; reading config")
                new_cfg = _runtime.load_config(path=config_path)
                info(f"config: {new_cfg}")
                return 0
    if not lavish_chosen:
        # Terminal prompt fallback. We walk the user through the
        # four key choices and write the result. This is the
        # primary path on machines without lavish-axi.
        info("terminal setup (lavish-axi not available or not chosen)")
        current_runtime = (config.get("runtime") or {}).get("default") or "claude"
        runtime = _prompt_user(
            "default runtime (claude / ollama / ollama-chat / openai-compatible)",
            default=current_runtime,
        ).strip().lower()
        if runtime not in _runtime.RUNTIMES:
            info(f"unknown runtime '{runtime}'; falling back to '{current_runtime}'")
            runtime = current_runtime
        model = _prompt_user(
            f"default model for {runtime}",
            default=_runtime.DEFAULT_MODELS.get(runtime, _runtime.DEFAULT_MODELS["claude"]),
        ).strip()
        if runtime == "ollama":
            mode = _prompt_user(
                "ollama mode (claude / chat) — claude = coding agent, chat = plain ollama REPL",
                default="claude",
            ).strip().lower()
            if mode not in ("claude", "chat"):
                mode = "claude"
        else:
            mode = ""
        backend = _prompt_user(
            "default backend (herdr / treehouse / none)",
            default="herdr",
        ).strip().lower()
        if backend not in ("herdr", "treehouse", "none"):
            backend = "herdr"
        ui_setup = "lavish-axi" if lavish_path and _yes_no(
            "use lavish-axi for setup pages? ", default_yes=False
        ) else "terminal"
        _write_setup_config(
            config_path,
            runtime=runtime,
            model=model,
            ollama_mode=mode,
            backend=backend,
            ui_setup=ui_setup,
        )
    info(f"wrote: {config_path}")
    info("next: try `agent-go --task code --print-prompt` to verify the config")
    if runtime == "ollama" and mode == "claude":
        info("claude-via-ollama will be used; install ollama and `ollama pull minimax-m3:cloud` if you have not")
    return 0


def _write_setup_config(
    path: Path,
    *,
    runtime: str,
    model: str,
    ollama_mode: str,
    backend: str,
    ui_setup: str,
) -> None:
    """Write a self-documenting `~/.agent-workbench/config.toml`.

    Each section has a one-line comment so the user can read the
    file and understand the choices without re-running `--setup`.
    Quoted values are used consistently for whitespace safety.
    """
    lines: list[str] = [
        "# agent-workbench configuration",
        "# Generated by `agent-go --setup`. Safe to edit by hand.",
        "",
        "[runtime]",
        f'default = "{runtime}"   # claude / ollama / ollama-chat / openai-compatible',
        "",
        "[claude]",
        f'model = "{_runtime.DEFAULT_MODELS["claude"]}"',
        "",
        "[ollama]",
        f'model = "{_runtime.DEFAULT_MODELS["ollama"]}"',
    ]
    if ollama_mode:
        lines.append(f'mode = "{ollama_mode}"   # claude = coding agent via ollama, chat = plain ollama REPL')
    lines.extend([
        "",
        "[ollama_chat]",
        f'model = "{_runtime.DEFAULT_MODELS["ollama-chat"]}"',
        "",
        "[openai_compatible]",
        'base_url = "http://localhost:1234/v1"   # LM Studio, vLLM, LiteLLM, etc.',
        'api_key_env = "OPENAI_API_KEY"',
        f'model = "{_runtime.DEFAULT_MODELS["openai-compatible"]}"',
        "",
        "[backend]",
        f'default = "{backend}"   # herdr / treehouse / none',
        "",
        "[ui]",
        f'setup = "{ui_setup}"   # lavish-axi / terminal',
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _bootstrap_if_needed(targets: list[str], *, allow_curl: bool, assume_yes: bool) -> int:
    """Install any missing dependency. Returns 0 on success, non-zero on failure."""
    statuses = _bootstrap.check_dependencies(targets)
    missing = [s for s in statuses if not s.present]
    if not missing:
        info("all requested tools already present")
        return 0
    if not assume_yes:
        names = ", ".join(s.name for s in missing)
        info(f"about to install: {names}")
        # In an interactive shell the user can already see the prompt; in
        # scripted runs pass --yes to skip the pause. (We don't actually
        # pause — we just announce. The installer is idempotent.)
    info(f"installing {len(missing)} missing tool(s) …")
    after = _bootstrap.install_dependencies(targets, allow_curl=allow_curl)
    still_missing = [s for s in after if not s.present]
    if still_missing:
        for s in still_missing:
            info(f"  ✗ {s.name}: {s.error or 'still missing'}")
        return 1
    info("all requested tools installed")
    return 0


def _herdr_server_running() -> bool:
    """Return True if a herdr server is reachable (socket present and responsive)."""
    herdr = resolve_executable("herdr")
    if not herdr:
        return False
    # `herdr status client` exits 0 when the socket answers.
    result = subprocess.run(
        [herdr, "status", "client"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.returncode == 0


def _start_herdr_server() -> bool:
    """Start the herdr server in the background. Returns True if it came up."""
    herdr = resolve_executable("herdr")
    if not herdr:
        return False
    if _herdr_server_running():
        info("herdr server already running")
        return True
    info("starting herdr server in the background …")
    # `herdr server` runs headless. We launch it detached so it survives
    # the agent-go process. On Windows we use CREATE_NEW_PROCESS_GROUP +
    # DETACHED_PROCESS to fully detach.
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([herdr, "server"], **kwargs)
    except OSError as exc:
        info(f"failed to start herdr server: {exc}")
        return False
    # Poll the socket for a few seconds — server comes up in <1s usually.
    import time
    for _ in range(20):
        time.sleep(0.25)
        if _herdr_server_running():
            info("herdr server is up")
            return True
    info("herdr server did not respond within 5s — continuing anyway")
    return False


def _spawn_via_herdr_agent(
    repo: Path,
    prompt_body: str,
    runtime: _runtime.Runtime,
    spawn_cmd: list[str],
    spawn_env: dict[str, str],
    *,
    auto_attach: bool = True,
) -> int:
    """Start a herdr agent that runs the given spawn_cmd (with env_overrides).

    Returns the herdr invocation's returncode. The agent runs in its own
    pane; the user can attach with `herdr agent attach <name>`. If
    `auto_attach` is True and stdout is a TTY, the function attempts
    to run `herdr agent attach <name>` as a blocking call so the user
    lands directly in the agent's pane. Set `auto_attach=False` (or
    pass `--no-attach` / `AGENT_GO_NO_AUTO_ATTACH=1`) to skip the
    attach and just print the manual instruction block.

    The `spawn_cmd` is the argv of the inner runner (`claude`,
    `ollama`, etc.). The first element of `spawn_cmd` is the runner's
    name; we resolve it to a real Windows executable (e.g. `claude.cmd`)
    before handing it to herdr so herdr's own `CreateProcessW` does not
    hit WinError 193 on the bare npm shim. The `spawn_env` dict is
    merged into the herdr process's environment so the inner runner
    inherits `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` for the
    openai-compatible and ollama (claude-via-ollama) runtimes.

    If herdr returns `agent_name_taken` (the agent name `primary`
    is already in use on the server), we retry with a unique
    name from `utils.unique_agent_name` (`primary-2`, `primary-3`,
    ..., `primary-<shortid>`). On exhaustion we fall back to
    `_spawn_direct`.
    """
    herdr = resolve_executable("herdr")
    if not herdr:
        return 1
    # First write the prompt to disk so we can pass --append-system-prompt-file.
    out = repo / AGENT_DIR_NAME / "SYSTEM_PROMPT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt_body, encoding="utf-8")
    info(f"prompt written: {out}")
    worktree_args = [
        herdr,
        "worktree",
        "create",
        "--cwd",
        str(repo),
        "--label",
        "agent-go",
        "--no-focus",
        "--json",
    ]
    wt_result = subprocess.run(worktree_args, capture_output=True, text=True, cwd=str(repo), timeout=30)
    if wt_result.returncode != 0:
        # herdr fails on fresh repos with no HEAD; on detached HEADs; or
        # when its own server socket is wedged. None of these is fatal —
        # we can still spawn the agent in the repo dir. Surface the
        # reason so the user can see what happened, then continue.
        info(
            f"herdr worktree create failed ({wt_result.stderr.strip()[:120] or 'no stderr'}); "
            f"running agent in repo root instead"
        )
        worktree_path = str(repo)
    else:
        # herdr emits a JSON envelope like:
        #   {"worktree_created":{"worktree":{"path":"C:\\...\\worktree-x",...},...}}
        # The previous code took stdout.strip() as the path, which meant
        # the entire JSON blob was passed as `--cwd` to `herdr agent
        # start`. herdr silently fell back to the user's home directory
        # on an invalid cwd, and the agent ended up in the wrong place.
        # Parse the JSON and pull the path out.
        payload = parse_json_loose(wt_result.stdout)
        worktree_path = _extract_worktree_path(payload) or str(repo)
        if payload and worktree_path == str(repo):
            info(
                f"herdr worktree create did not return a path; "
                f"running agent in repo root instead"
            )
    # Resolve the inner runner (claude / ollama) to a real Windows
    # executable (e.g. `claude.cmd`) before handing it to herdr, so
    # herdr's own CreateProcessW call does not hit WinError 193 on
    # the bare npm shim.
    inner_name = spawn_cmd[0]
    inner_resolved = resolve_executable(inner_name)
    if not inner_resolved:
        info(f"{inner_name} executable not found; falling back")
        return _spawn_direct(repo, runtime, spawn_cmd, spawn_env)
    # The ollama-chat runtime's runner is `ollama.exe` and does not
    # understand --append-system-prompt (that is a Claude Code flag).
    # We drop the prompt arg and rely on .agent/SYSTEM_PROMPT.md
    # being written; the user can paste the prompt into the pane.
    # The ollama (claude-via-ollama), openai-compatible, and claude
    # runtimes all reuse the claude CLI, so they accept
    # --append-system-prompt normally.
    if inner_name == "ollama":
        inner_argv = [inner_resolved, *spawn_cmd[1:]]
    else:
        inner_argv = [inner_resolved, *spawn_cmd[1:], "--append-system-prompt", prompt_body]
    cmd = [
        herdr,
        "agent",
        "start",
        None,  # placeholder for the agent name; filled in below
        "--cwd",
        worktree_path,
        "--split",
        "right",
        "--no-focus",
        "--",
        *inner_argv,
    ]
    # Merge spawn_env into the herdr process's environment so the
    # inner runner inherits ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN
    # for the openai-compatible and ollama (claude-via-ollama)
    # runtimes. herdr itself does not read these vars; the inner
    # claude process does.
    child_env = None
    if spawn_env:
        child_env = os.environ.copy()
        child_env.update(spawn_env)
    # Retry loop. We try `primary`, then `primary-2`..`primary-5`,
    # then `primary-<shortid>`. Total budget is 8 attempts. On
    # exhaustion we fall back to direct.
    MAX_AGENT_NAME_ATTEMPTS = 8
    for attempt in range(MAX_AGENT_NAME_ATTEMPTS):
        agent_name = unique_agent_name("primary", attempt)
        cmd[3] = agent_name
        info(f"starting herdr agent '{agent_name}' in {worktree_path}")
        # Capture stdout so we can read herdr's `agent_started`
        # JSON envelope and verify the agent actually started in
        # the cwd we asked for. The previous code discarded stdout
        # and only printed a single line, which masked the
        # "agent started in $HOME" bug.
        result = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, env=child_env)
        if result.returncode == 0:
            # Print the 7-line pre-launch block (command / agent /
            # cwd / backend) so the user sees the resolved spawn
            # shape even after a retry. The runtime / mode / model
            # lines were already printed before the spawn attempt.
            backend_name = "herdr"
            extra_lines = _runtime.runtime_summary_lines(
                runtime,
                command=inner_argv,
                agent=agent_name,
                cwd=worktree_path,
                backend=backend_name,
            )
            # Skip the first 3 (runtime / mode / model) since we
            # already printed them, and any base_url line. We print
            # everything from the 4th line onward.
            for line in extra_lines[3:]:
                info(line)
            # Pull the actual cwd herdr used from the
            # `agent_started` envelope.
            started_payload = parse_json_loose(result.stdout)
            actual_cwd, reported_name = _extract_agent_info(started_payload)
            actual_cwd = actual_cwd or worktree_path
            if reported_name:
                agent_name = reported_name
            # Warn if herdr's reported cwd does not match what we
            # asked for.
            if actual_cwd and worktree_path and _paths_differ(actual_cwd, worktree_path):
                info(
                    f"herdr agent started in {actual_cwd}, expected {worktree_path}; "
                    f"the agent may be in the wrong directory"
                )
            _print_attach_instructions(repo=repo, worktree=worktree_path, actual_cwd=actual_cwd, agent_name=agent_name)
            if auto_attach and _should_auto_attach():
                return _auto_attach(herdr, agent_name)
            return 0
        # Non-zero exit. Check for agent_name_taken and retry.
        if is_agent_name_taken_error(result.stdout, result.stderr):
            info(
                f"herdr agent '{agent_name}' already exists on the server; "
                f"retrying with a unique name"
            )
            continue
        # Any other failure is real. Surface the stderr and fall back.
        info(
            f"herdr agent start failed (exit {result.returncode}); "
            f"stderr: {result.stderr.strip()[:200] or '(empty)'}; "
            f"falling back to direct {inner_name}"
        )
        return _spawn_direct(repo, runtime, spawn_cmd, spawn_env)
    # Retry budget exhausted — fall back to the direct path.
    info(
        f"could not find a unique herdr agent name after {MAX_AGENT_NAME_ATTEMPTS} attempts; "
        f"falling back to direct {inner_name}"
    )
    return _spawn_direct(repo, runtime, spawn_cmd, spawn_env)


def _spawn_direct(
    repo: Path,
    runtime: _runtime.Runtime,
    spawn_cmd: list[str],
    spawn_env: dict[str, str],
) -> int:
    """Spawn the runner in the current shell (no herdr isolation).

    Used as the direct fallback when herdr is not available, when
    `--no-herdr` is set, or when the herdr spawn fails. For the
    `claude` runtime, the prompt is appended; for `ollama` the
    prompt is left to the user to paste in. For
    `openai-compatible`, the env overrides are applied.
    """
    runner_name = spawn_cmd[0]
    runner_path = resolve_executable(runner_name)
    if not runner_path:
        info(f"{runner_name} executable not found on PATH")
        if runtime.is_claude():
            return _spawn_ollama(repo, runtime.model)
        return 127
    argv = [runner_path, *spawn_cmd[1:]]
    if runtime.is_claude() or runtime.is_openai_compatible():
        # Claude Code accepts the prompt via --append-system-prompt.
        # The prompt is also written to .agent/SYSTEM_PROMPT.md so
        # Claude Code auto-loads it on its own.
        prompt_path = repo / AGENT_DIR_NAME / "SYSTEM_PROMPT.md"
        argv.extend(["--append-system-prompt", prompt_path.read_text(encoding="utf-8")])
    info(f"running: {runner_path} (cwd={repo}, runtime={runtime.name}, model={runtime.model})")
    child_env = None
    if spawn_env:
        child_env = os.environ.copy()
        child_env.update(spawn_env)
    result = subprocess.run(argv, cwd=str(repo), env=child_env)
    return result.returncode


def _spawn_claude(repo: Path, model: str) -> int:
    """Launch the `claude` CLI in the current repo (no herdr isolation)."""
    return _spawn_direct(
        repo,
        _runtime.Runtime(name="claude", model=model, source="legacy"),
        ["claude", "--model", model],
        {},
    )


def _spawn_ollama(repo: Path, model: str) -> int:
    """Final fallback: `ollama run <model>`."""
    ollama = resolve_executable("ollama")
    if not ollama:
        info("no model runner found (claude and ollama both missing)")
        info("install one with:  agent-go --bootstrap=claude    # or --bootstrap=ollama")
        return 127
    info(f"running: {ollama} run {model} (cwd={repo})")
    result = subprocess.run([ollama, "run", model], cwd=str(repo))
    return result.returncode


def _print_one_liner() -> int:
    """Print the PowerShell one-liner the user pastes on a fresh machine."""
    repo = "C:\\path\\to\\your\\repo"
    if os.name == "nt":
        print(
            "iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1); "
            f"cd '{repo}'; agent-go"
        )
    else:
        print(
            "curl -fsSL https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.sh | sh; "
            f"cd {repo}; agent-go"
        )
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    """Build the argparse parser for `agent-go`.

    Extracted from `main()` so tests can drive the parser directly
    (e.g. to verify the `--runtime` / `--base-url` / `--api-key-env`
    flags land in the right `args` attributes)."""
    parser = argparse.ArgumentParser(
        description="One-liner cold-machine bootstrap: install missing tools, start herdr, run the model with global rules.",
    )
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (auto-detected).")
    parser.add_argument(
        "--task",
        choices=("code", "review", "architecture", "documentation", "general"),
        default="general",
        help="Which task-specific agent prompt to layer in.",
    )
    parser.add_argument(
        "--runtime",
        choices=_runtime.RUNTIMES,
        default=None,
        help="Which model runner to use (default: from AGENT_RUNTIME or config). "
             "claude=Anthropic Claude Code, ollama=Claude Code via local Ollama, "
             "ollama-chat=plain `ollama run` REPL, "
             "openai-compatible=Claude Code pointed at ANTHROPIC_BASE_URL.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the model name. Default per runtime: claude=opus, "
             "ollama=minimax-m3:cloud, ollama-chat=minimax-m3:cloud, "
             "openai-compatible=minimax-m3:cloud.",
    )
    parser.add_argument(
        "--backend",
        choices=("herdr", "treehouse", "none"),
        default=None,
        help="Which orchestrator to use (default: from [backend] default "
             "in config, or herdr).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="(openai-compatible) The Anthropic-protocol base URL "
             "(e.g. http://localhost:1234/v1 for LM Studio).",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="(openai-compatible) Name of the env var holding the API key "
             "(e.g. OPENAI_API_KEY). The value is read at spawn time.",
    )
    parser.add_argument(
        "--bootstrap",
        default=",".join(DEFAULT_GO_BOOTSTRAP),
        help=f"Comma-separated list of tools to ensure installed (default: {','.join(DEFAULT_GO_BOOTSTRAP)}).",
    )
    parser.add_argument("--no-bootstrap", action="store_true", help="Skip the install step; assume everything is present.")
    parser.add_argument("--no-curl", action="store_true", help="Skip install methods that pipe a remote shell.")
    parser.add_argument("--no-herdr", action="store_true", help="Don't start the herdr server; run the model in the current shell.")
    parser.add_argument(
        "--no-attach",
        action="store_true",
        help="Don't auto-attach the user's terminal to the herdr agent. "
             "Print the manual instruction block instead. Equivalent to "
             "setting the AGENT_GO_NO_AUTO_ATTACH=1 environment variable.",
    )
    parser.add_argument("--yes", action="store_true", help="Assume yes for any install prompts (default: assume yes; flag exists for symmetry).")
    parser.add_argument(
        "--print-cmd",
        action="store_true",
        help="Print the one-liner for a fresh machine and exit (no install, no run).",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Print the assembled prompt to stdout and exit. Skips the install step, "
             "the herdr server, and the model launch. Use this for a read-only view of "
             "the prompt, or to capture the prompt to a file.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Interactively write ~/.agent-workbench/config.toml. "
             "If lavish-axi is installed, defer to it; otherwise prompt "
             "in the terminal. Safe to re-run; the existing file is "
             "preserved unless you confirm overwrite.",
    )
    parser.add_argument(
        "task_text",
        nargs="?",
        default="",
        help="Optional task description appended to the prompt.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)

    # --setup is the early-branching path: it does not need a
    # repo, an install, or a runtime resolution. We run it before
    # any other logic.
    if args.setup:
        return _run_setup_interactive(_runtime.CONFIG_PATH)

    # Load the workbench config up-front so both --print-prompt and
    # the runtime resolution layers see the same view of the file.
    config = _runtime.load_config()

    if args.print_cmd:
        # --print-cmd is runtime-agnostic: the one-liner does not change
        # when the runtime does. But we still print what would be used
        # so docs reviewers can see the resolved runtime + model.
        rt_name, rt_source = _runtime.resolve_runtime(
            cli_value=args.runtime,
            env_value=os.environ.get("AGENT_RUNTIME"),
            config=config,
        )
        rt_model, _ = _runtime.resolve_model(
            rt_name,
            cli_model=args.model,
            env_model=os.environ.get("AGENT_MODEL"),
            config=config,
        )
        info(f"resolved runtime: {rt_name} (from {rt_source})")
        info(f"resolved model:   {rt_model}")
        return _print_one_liner()

    repo = (args.repo or find_repo_root()).resolve()
    info(f"repo: {repo}")

    # Resolve the runtime up-front so both the read-only path
    # (--print-prompt) and the actual launch can print the same
    # "what we are going to use" block.
    rt_name, rt_source = _runtime.resolve_runtime(
        cli_value=args.runtime,
        env_value=os.environ.get("AGENT_RUNTIME"),
        config=config,
    )
    rt_model, model_source = _runtime.resolve_model(
        rt_name,
        cli_model=args.model,
        env_model=os.environ.get("AGENT_MODEL"),
        config=config,
    )
    # Resolve the ollama mode so the pre-launch block can surface
    # `runtime mode: claude-via-ollama` vs `runtime mode: chat`
    # for the ollama / ollama-chat runtimes. The mode field is
    # informational for the summary; `build_spawn_args` is the
    # source of truth for what the actual command does.
    if rt_name == "ollama":
        ollama_mode = _runtime.resolve_ollama_mode(config)
    elif rt_name == "ollama-chat":
        ollama_mode = "chat"
    else:
        ollama_mode = "default"
    runtime = _runtime.Runtime(
        name=rt_name,
        model=rt_model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        source=rt_source,
        mode=ollama_mode,
    )
    # The pre-launch output block. We print the runtime / mode /
    # model / base_url lines now; the command / agent / cwd /
    # backend lines are filled in by the spawn function once we
    # know the resolved spawn argv and the herdr worktree path.
    for line in _runtime.runtime_summary_lines(runtime):
        info(line)
    info(f"runtime source:  {rt_source}")
    info(f"model source:    {model_source}")

    # Step 1: assemble the prompt. Done up-front so the read-only paths
    # (`--print-prompt`) can return before the install step touches the
    # network. The previous order (install, then assemble) made
    # `agent-go --print-prompt` produce a noisy "no asset" error from
    # the gnhf install on Windows even though the user never asked to
    # launch anything.
    body, loaded = assemble_prompt(repo, task=args.task)
    if args.task_text:
        body = body.rstrip() + "\n\n## Task\n\n" + args.task_text.strip() + "\n"
    info(f"prompt: {len(body):,} bytes from {len(loaded)} file(s)")
    if args.print_prompt:
        # Pure read path. No install, no herdr, no model launch.
        # The runtime resolution already printed; the prompt body
        # follows on stdout for piping / diffing.
        sys.stdout.write(body)
        return 0

    # Step 2: install missing tools (unless told to skip). Only reached
    # on the actual run path; `--print-prompt` already returned above.
    if not args.no_bootstrap:
        targets = [t.strip() for t in args.bootstrap.split(",") if t.strip()]
        rc = _bootstrap_if_needed(targets, allow_curl=not args.no_curl, assume_yes=args.yes)
        if rc != 0:
            info("some tools could not be installed; continuing with what we have")
    _ensure_path()
    _print_path_hint_if_needed()

    # Step 3: write the prompt to .agent/SYSTEM_PROMPT.md so Claude Code
    # auto-loads it via its CLAUDE.md discovery.
    out = repo / AGENT_DIR_NAME / "SYSTEM_PROMPT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    info(f"wrote {out}")

    # Step 4: Claude-login probe. If the user selected the claude
    # runtime and Claude is not logged in, print the fallback
    # message and exit 0. We do not even start herdr in this case
    # because the only outcome is a broken pane.
    if runtime.is_claude() and not _runtime.claude_logged_in():
        info("Claude Code is not logged in and no ANTHROPIC_API_KEY is set.")
        info(_runtime.claude_missing_login_message(task=args.task))
        return 0

    # Step 5: build the spawn argv + env for the resolved runtime.
    spawn_cmd, spawn_env = _runtime.build_spawn_args(
        runtime,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
    )
    info(f"spawn: {' '.join(spawn_cmd)}")

    # Step 6: start herdr in the background, unless asked not to.
    herdr_up = False
    if not args.no_herdr:
        herdr_up = _start_herdr_server()

    # Step 7: launch the model. The claude and openai-compatible
    # runtimes use the herdr pane path (with auto-attach); the
    # ollama runtime uses the herdr pane path too (we just spawn
    # `ollama run` inside the pane instead of `claude`). The
    # --no-herdr path drops back to the direct (in-shell) spawn.
    auto_attach = not args.no_attach
    if herdr_up and not args.no_herdr:
        return _spawn_via_herdr_agent(
            repo, body, runtime, spawn_cmd, spawn_env, auto_attach=auto_attach
        )
    return _spawn_direct(repo, runtime, spawn_cmd, spawn_env)


if __name__ == "__main__":
    raise SystemExit(main())
