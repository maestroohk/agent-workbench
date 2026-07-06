# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Runtime / provider selection for `agent-go`, `agent-claude`,
  and `agent-fleet`.** Three first-class runtimes:
  - `claude` — Anthropic Claude Code (default).
  - `ollama` — local Ollama (`ollama run <model>`).
  - `openai-compatible` — Claude Code pointed at a custom
    `ANTHROPIC_BASE_URL`, for LM Studio, vLLM, LiteLLM, and any
    provider that speaks the Anthropic wire protocol through that
    env var.

  Selection order: **CLI > env > config > default** for both the
  runtime name and the model name. CLI flags live on every
  `agent-go` / `agent-claude` / `agent-fleet` invocation
  (`--runtime`, `--model`, `--base-url`, `--api-key-env`); the env
  vars are `AGENT_RUNTIME` and `AGENT_MODEL`; the config file
  lives at `~/.agent-workbench/config.toml` with four sections
  (`[runtime]`, `[claude]`, `[ollama]`, `[openai_compatible]`).

  Default model is **runtime-specific**: `opus` for `claude`,
  `minimax-m3:cloud` for `ollama` and `openai-compatible`. The
  legacy top-level `model = "..."` config form is honored as a
  fallback so existing users don't have to migrate.

- **Claude Code login detection.** `agent-go` (and
  `agent-claude`) now probe `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`,
  `$CLAUDE_CONFIG_DIR/.credentials.json`, `~/.claude/.credentials.json`,
  and the legacy `~/.claude.json` before launching. If none are
  set, the user gets the documented fallback message and exits 0
  instead of being dropped into a broken pane that says
  `Not logged in · Run /login`:
  ```
  Claude Code opened but is not logged in.
  Run `/login` inside Claude, or use:
    agent-go --task code --runtime ollama --model <model>
    agent-go --task code --runtime openai-compatible --model <model> --base-url <url>
  ```

- **`scripts/python/runtime.py`** — the single source of truth for
  runtime resolution. Exports `Runtime` (frozen dataclass),
  `RUNTIMES` (canonical list), `DEFAULT_MODELS` (runtime-specific),
  `load_config()`, `resolve_runtime()`, `resolve_model()`,
  `claude_logged_in()`, `claude_missing_login_message()`,
  `build_spawn_args(runtime)` (the `(cmd, env_overrides)` factory),
  and `runtime_summary_lines()`. Uses a small line-based parser
  for the four-section config; no `tomli` dependency.

- **`agent-go --print-cmd` and `--print-prompt` are now
  runtime-aware.** The resolved runtime + model + base_url (for
  `openai-compatible`) is printed at the top of the output so
  docs reviewers can see what would be used without launching
  anything.

- **`--backend` is now orthogonal to `--runtime` on
  `agent-claude` and `agent-fleet`.** `--backend` picks the
  multi-agent orchestrator (herdr / treehouse / none for
  `agent-fleet`; herdr / claude / ollama / none for
  `agent-claude`); `--runtime` picks the model runner
  (claude / ollama / openai-compatible). The herdr and treehouse
  backends require `--runtime=claude` (herdr's `agent start` is
  hardcoded to call the claude CLI via its integration hook);
  the ollama and openai-compatible runtimes route to direct
  spawn in the current shell.

- **`utils.run_command()` now accepts an `env=` kwarg.** The
  `openai-compatible` runtime uses this to inject
  `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` into the
  child's environment without mutating the current process's
  environment. When `env=` is not passed, behaviour is unchanged
  (the child inherits the parent env).

- **`tests/test_runtime_provider.py`** — 53 regression tests
  covering `resolve_runtime` (CLI > env > config > default,
  unknown values fall through), `resolve_model` (runtime-specific
  defaults, per-runtime config section, legacy top-level model
  key), `load_config` (four sections, comments, blank lines,
  missing/garbage file, `openai_compatible` -> `openai-compatible`
  normalisation, OSError on read), `claude_logged_in` (env vars,
  credentials file, legacy `.claude.json`, whitespace-treated-as-unset,
  isolated `Path.home()` for the no-credentials case),
  `claude_missing_login_message` (exact text from the spec),
  `build_spawn_args` (claude / ollama / openai-compatible,
  base-url + api-key-env kwargs, empty api-key value, unknown
  runtime falls back to claude), `runtime_summary_lines` (with /
  without base_url), and `agent_go.main` integration (the
  `--runtime` / `--model` / `--base-url` / `--api-key-env` flags
  parse, `--print-prompt` includes the runtime line,
  `--runtime claude` with no login prints the fallback message
  and exits 0, `--runtime claude` with a credentials file proceeds
  past the login probe, `--runtime ollama` skips the login probe).

- **`tests/test_agent_runtime_wiring.py`** — 25 regression tests
  covering the new wiring in `agent-claude` and `agent-fleet`:
  argparse (`--runtime` / `--base-url` / `--api-key-env` land in
  the right `args` attributes; `--backend` stays orthogonal);
  `agent_claude._resolve_full_runtime` (CLI > env > config >
  default); `agent_fleet._resolve_backend` (claude runtime
  prefers herdr; ollama and openai-compatible fall back to
  `none`); the `agent_claude._spawn_claude` spawn paths (ollama
  uses `ollama run <model>`; claude and openai-compatible use
  `claude --model <model>`; only the openai-compatible path
  injects env overrides); the `agent_fleet._spawn_none` spawn
  paths (same env-override contract; the no-runner case writes
  prompts only); and `utils.run_command` with and without
  `env=`.

### Fixed
- **`agent-go --task code` opened Claude Code in herdr but
  landed the user in a pane that said "Not logged in".** A user
  without an Anthropic subscription had no documented path to a
  working session. The runtime layer (above) gives them one: the
  login probe prints the fallback message up-front, and the
  `--runtime ollama` / `--runtime openai-compatible` flags route
  to a working session.

### Fixed
- **`agent-go --task code` now lands the agent in the worktree path,
  not the user's home directory.** A previous version of the shim
  passed `wt_result.stdout.strip()` as `--cwd` to `herdr agent
  start`, but `wt_result.stdout` is the entire
  `worktree_created` JSON envelope (e.g.
  `{"worktree_created":{"worktree":{"path":"C:\\..."}}}`),
  which herdr rejected by silently falling back to `$HOME`.
  The shim now parses the envelope with a new
  `utils.parse_json_loose()` helper (tolerant of leading
  non-JSON noise and trailing garbage) and passes the actual
  `worktree.path` string. The same fix applies to
  `agent-claude --backend=herdr` and `agent-fleet --backend=herdr`,
  which had the same bug. A Windows path with backslashes and
  spaces (`C:\Users\Test User\repos\My App\worktree-x`)
  round-trips intact.
- **`agent-go` now verifies the agent's actual cwd.** After
  `herdr agent start` returns, the shim parses the
  `agent_started` JSON envelope (`{"agent_started":{"agent":"...","cwd":"...","argv":[...]}}`)
  and compares `agent_started.cwd` to the requested worktree
  path. If herdr landed the agent somewhere else, a `[warn]`
  line is printed instead of silently claiming success. Path
  comparison is normalized (`os.path.normcase` /
  `os.path.normpath`) so backslash/forward-slash and
  case differences don't trigger spurious warnings.
- **`agent-go` now prints a clear instruction block after
  spawning the agent.** The block contains the repo root, the
  worktree path, the agent's actual cwd, the agent name, and
  the `herdr agent attach <name>` command. This is what was
  missing in the previous version — the user was returned to
  the PowerShell prompt with no obvious next step.
- **`agent-go` now attempts to auto-attach the user's terminal
  to the running herdr agent.** Once the agent is up, the shim
  calls `herdr agent attach <name>` as a foreground blocking
  TTY call so the user lands directly in the agent's pane.
  Auto-attach is enabled when stdout is a TTY and the env var
  `AGENT_GO_NO_AUTO_ATTACH` is not set to a truthy value
  (`1` / `true` / `yes` / `on`). If `herdr agent attach`
  returns non-zero, the agent is still running and the
  instruction block tells the user how to attach manually.
- **New `--no-attach` flag for `agent-go`**. Suppresses the
  auto-attach attempt; the instruction block is the last
  thing printed before exit 0. Useful for CI / scripted use
  where attaching the agent pane is not desired.
- **`agent-fleet` does not auto-attach.** With N agents,
  auto-attach would only work for one of them, so the shim
  prints the `herdr agent attach <name>` command for every
  agent and exits. The user attaches to any agent by name.
- **New `utils.parse_json_loose(text)` helper.** Tries
  `json.loads(text)` first; on `JSONDecodeError`, scans for
  the first balanced `{...}` substring and returns the first
  parseable dict. Returns `None` on empty / non-JSON input.
  Used by every herdr shim to extract fields from herdr's
  JSON envelopes, which sometimes have leading status lines
  (e.g. `herdr: creating worktree...`).

### Added
- **`tests/test_herdr_json_parsing.py`** — 37 regression tests
  covering the new `parse_json_loose` helper (clean object,
  leading non-JSON noise, multiline pretty-printed, empty
  string, whitespace, plain text, non-dict JSON, trailing
  garbage, Windows path with spaces); the worktree-path
  extraction (envelope shape `{"worktree_created":...}`,
  top-level `{"path":"..."}`, `None` / empty input, wrong
  inner types); the agent-info extraction (envelope shape,
  top-level shape, `None` input, missing cwd, missing name,
  `name` alias for `agent`); path normalization
  (`os.path.normcase` / `os.path.normpath`, with Windows
  backslash/forward-slash and case-insensitivity tests gated
  on `sys.platform`); end-to-end `subprocess.run`
  monkeypatching that verifies `--cwd` in the
  `herdr agent start` call is the extracted worktree path
  (not the raw JSON); cwd-mismatch warning; instruction
  block content; and auto-attach opt-out (`AGENT_GO_NO_AUTO_ATTACH`
  env var, `--no-attach` flag, non-TTY stdout). All
  37 tests pass alongside the prior 55.

### Fixed
- **`agent-go` no longer fails silently when herdr cannot place an
  agent on Windows (or anywhere else).** The shim now passes
  `--cwd <repo>` to `herdr worktree create` (mandatory when no
  workspace is active), uses `--split right --no-focus` for
  `herdr agent start <name>` (the documented placement flag —
  `--tab new` is rejected by herdr because `--tab` expects an
  existing tab ID, not the literal `new`), and falls back to
  direct `claude` with a clear info line if herdr errors.
  Previously, a herdr placement failure returned 0 silently and
  the user was dropped back at the PowerShell prompt with no
  pane and no message.
- **`agent-go --no-herdr` (and `agent-claude --backend=claude`) no
  longer hit `WinError 193` on Windows.** Both now resolve
  `claude` to `claude.cmd` (or the first `.bat` / `.exe` form
  on PATH) before calling `subprocess.run`. The bug was that
  the bare `claude` shim on `%APPDATA%\npm` is a Node.js script,
  not a PE binary, and `CreateProcessW` rejects it with
  `'%1 is not a valid Win32 application'`. herdr's own
  `CreateProcessW` is fixed the same way: the inner `claude` is
  resolved to its absolute `claude.cmd` path before being passed
  to herdr.
- **`agent-go --print-prompt` is now a true no-op read path:**
  no install, no herdr, no model launch. The previous behavior
  ran the full bootstrap first, which tried to install `gnhf`
  (overnight-only) and produced a noisy `no asset matching`
  error on Windows before the user ever saw their prompt.
- **`agent-go`'s default bootstrap no longer includes `gnhf`**
  (overnight-only, not used by interactive `agent-go`). The slim
  default is now `claude, herdr, firstmate, no-mistakes, ollama`.
  gnhf is one `--bootstrap=gnhf` away. `treehouse` is opt-in
  for the same reason (worktree pool; `agent-fleet` is the
  path that wants it).
- **New `WINDOWS_USAGE.md`** with the step-by-step Windows
  quickstart, troubleshooting for the three silent failures
  above, and the `--no-herdr` / `--print-prompt` fallback
  paths. Linked from the README's "Cold-machine flow" section.

### Added
- **`utils.resolve_executable(name)`** — the single source of
  truth for Windows command resolution. On Windows it tries
  `name.cmd`, `name.bat`, `name.exe` in that order before
  falling back to the bare name, so `subprocess.run` no longer
  hits `WinError 193` on npm shims. On non-Windows it is a
  one-liner that returns `shutil.which(name)` unchanged. Used
  everywhere `agent_go` and `agent_claude` spawn `claude`,
  `ollama`, or `herdr` (including the inner `claude` passed to
  herdr's `agent start`).
- **`tests/test_windows_command_resolution.py`** — 16 regression
  tests covering `resolve_executable` (Windows .cmd preference,
  bare fallback, already-suffixed input, .exe fallback), the
  `DEFAULT_GO_BOOTSTRAP` slim default (`gnhf` and `treehouse`
  out; hot-path tools in), `--print-prompt` short-circuit (no
  install, no herdr, no model launch), the `_spawn_claude`
  argv contract (resolved .cmd, not bare shim), and the
  `_spawn_via_herdr_agent` fallback contract (worktree create
  failure → repo root + `--split right`; agent start failure →
  direct `claude`).

### Fixed
- **Windows PowerShell shims no longer reject unknown args** (`--help`,
  `-h`, custom flags) at the PowerShell layer. Every
  `scripts/powershell/agent-*.ps1` is now a thin pass-through: a
  single `[Parameter(ValueFromRemainingArguments=$true)] [string[]]$Rest`
  captures all user args and forwards them verbatim to
  `dispatch.py <verb> @Rest`. This eliminates the bug class where the
  shim's hand-rolled `$forward` rebuild could inject empty `--repo`
  (or other default-valued flag) before the user's args reached the
  inner argparse, producing the
  `dispatch.py: error: argument --repo: expected one argument` error
  on `agent-go --task code`, `agent-scan --help`, etc. The inner
  python module's argparse is now the single source of truth for
  argument validation. Affects: `agent-go`, `agent-scan`,
  `agent-check`, `agent-init`, `agent-bootstrap`, `agent-review`,
  `agent-test`, `agent-claude`, `agent-fleet`, `agent-overnight`,
  `agent`.
- **`agent-review` (no args) preserves its legacy default of
  `--task review --show-files`.** The shim used to inject those
  by hand; the defaults now live in `build_prompt.py`'s argparse
  (where they belong), so the shim's removal does not change the
  user-facing behavior. A `--no-show-files` flag was added for the
  inverse case.

### Added
- **`tests/test_shim_argument_forwarding.py`** with 17 tests
  covering the `dispatch.py -> command.main()` chain that the
  shim now invokes. Asserts that `--help` reaches the inner
  argparse for every verb, that `--task code`, `--repo .`,
  `--repo <abs>`, and `--print-cmd` all work without an injected
  empty `--repo`, and that the user's exact failing commands
  (`agent-go --task code`, `agent-scan --help`, etc.) produce no
  "expected one argument" error. Run with
  `python -m pytest tests/test_shim_argument_forwarding.py -v`.
- **`tests/` directory with three test files** (`test_path_handling.py`,
  `test_shell_profile_respect.py`, `test_tool_discovery.py`).
  Coverage: Windows path resolution (backslashes, spaces, POSIX
  paths), installer shell-profile respect (no silent writes to
  `~/.bashrc` / `~/.zshrc` / HKCU PATH), and tool discovery
  (role taxonomy, slim default set, `presence_hint` fallback).
  Run with `pip install -r requirements-dev.txt && python -m pytest
  tests/ -v`. 22 tests, all passing.
- **`requirements-dev.txt`** with `pytest>=7.0` so the test suite is
  a one-line install.
- **`role` key on every `DEPENDENCIES` entry** in
  `scripts/python/bootstrap.py`. Each tool is now classified by its
  place in the workflow, not by its install method. The eight roles
  are: `orchestrator` (firstmate), `visual-collaboration` (lavish-axi),
  `isolation-manager` (treehouse), `validation-gate` (no-mistakes),
  `overnight-runner` (gnhf), `agent-runtime` (herdr),
  `model-runtime` (claude, ollama), `terminal-fallback` (wezterm).
  See `tools/roles.md` for the full mapping. The `role` key is on
  the internal `DEPENDENCIES` table only; `check_dependencies()` and
  `DependencyStatus` keep their public signatures.

### Changed
- **`install.sh` no longer silently edits `~/.bashrc` or `~/.zshrc`**.
  Replaces the auto-append loop with a one-time message that prints
  the export line and the right file to add it to (detected from
  `$SHELL`: `~/.bashrc` for bash, `~/.zshrc` for zsh,
  `~/.config/fish/config.fish` for fish, or a generic hint for
  anything else). Session-only PATH is still set so the rest of the
  installer (and any tools run in the same session) can resolve the
  shims. This is a behavior change on clean installs: the user now
  has to copy one line into their rc instead of having it appended.
- **`install.ps1` now asks before persisting HKCU user PATH**.
  The unconditional `[Environment]::SetEnvironmentVariable('Path',
  ..., 'User')` call is replaced with a `Read-Host` prompt that
  shows the proposed new `Path` value and asks "Apply this change?
  [y/N]". The session-only `$env:Path` is still set unconditionally
  so the rest of the installer works. The user can answer `N` and
  run the installer the same way as before, just without the
  registry write. Scripted installs can pipe `y` to opt in.
- **Docs now reflect a role-based mental model**. New
  `tools/roles.md` documents the eight roles
  (`orchestrator`, `visual-collaboration`, `isolation-manager`,
  `validation-gate`, `overnight-runner`, `agent-runtime`,
  `model-runtime`, `terminal-fallback`) and the 9-step workflow.
  `tools/firstmate.md` drops the `firstmate test` / `firstmate
  doctor` / `firstmate build` claims and points at the role it fills
  (`orchestrator`). `AGENTS.md` adds a section 8 ("Roles and the
  workflow") and strengthens the Boundaries section to forbid silent
  modifications to dotfiles / PATH / Git config. `README.md` adds a
  "Mental model" section with the 9-step workflow and a Roles
  table; the Dependencies table annotates each tool with its role;
  the "Other tools" sentence in Usage no longer mentions
  `firstmate test`.
- **`DEFAULT_BOOTSTRAP_SET` slimmed** from
  `("herdr", "firstmate", "no-mistakes", "treehouse")` to
  `("herdr", "firstmate", "no-mistakes")`. `treehouse` is opt-in via
  `--bootstrap=treehouse` (or `--bootstrap=all`) because a
  single-agent flow does not need a worktree pool. The
  `agent-fleet --backend treehouse` path still works — the worktree
  binary is just not pulled in by the default install.

### Fixed
- **`bootstrap` firstmate probe was wrong**: the `firstmate` entry in
  `DEPENDENCIES` had `probe: "claude"`, so the installer reported
  "firstmate: already present at ...npm/claude" on every machine
  with the Claude CLI and never actually cloned the firstmate
  harness. Now probes by `"firstmate"` (the shim name) and falls
  back to the `${HOME}/firstmate/AGENTS.md` presence hint. A new
  post-install hook system drops a `firstmate` shim in
  `~/.local/bin/` that dispatches to the harness's `bin/fm-*.sh`
  scripts, so callers get a stable command name.
- **`agent-check` no longer pretends to call non-existent firstmate
  subcommands**: dropped the `firstmate.toml` requirement from
  `firstmate_present()` (the format doesn't exist upstream) and
  replaced the fake "firstmate doctor passed" line with a real
  preflight that reports the harness path, the most recent commit,
  the shim resolution, and the count of `bin/fm-*.sh` scripts.
  `firstmate build` is now a documented no-op ("no build subcommand
  upstream (workbench skips)"). Verified on Windows: `agent-check`
  on `~/code/lavish-demo` now reports firstmate truthfully.
- **`gnhf` install no longer runs `npm install -g gnhf`**: gnhf is a
  Go binary at `github.com/kunchenguid/gnhf`, not an npm package.
  Now uses the same `_github_release` path as no-mistakes and
  treehouse. As of 2026-07-06, `gnhf` ships no Windows release, so
  the install on Windows surfaces an honest "no asset matching ...
  (have: [])" error rather than a silent npm failure.
- **`_install_from_github_release` is robust to tags that already
  start with the binary name**: `gnhf`'s tags are `gnhf-v0.1.42`
  etc., so the asset name pattern `<binary>-<tag>-<os>-<arch>` would
  have produced `gnhf-gnhf-v0.1.42-...`. The tag is now stripped of
  a single leading `<binary>-` if present. No effect on no-mistakes
  or treehouse.
- **`subprocess.run(['npm', ...])` and `subprocess.run(['npx', ...])`
  on Windows**: `shutil.which('npm')` returns the bare `npm` shim
  (a Node.js script, not a PE binary), which `CreateProcess` rejects
  with `WinError 193`. The PowerShell-path resolution in
  `_run_method` now also falls back to `name.cmd` for any command
  whose resolved path is not a recognized Windows executable
  extension. This unblocks the `claude` and `ollama` install paths
  too (both had the same latent bug; masked because both were
  pre-installed on the test machine).
- **No-mojibake subprocess output**: `run_command` in `utils.py` was
  decoding captured output with the default locale (cp1252 on
  Windows), which crashed on `no-mistakes doctor`'s UTF-8 checkmarks
  and rendered them as `âœ"` in the report. Now decodes as UTF-8
  with `errors="replace"`. Visible improvement: the
  `no-mistakes doctor` info lines now render `✓` and `–` correctly.
- **Windows + Git Bash now resolves `agent-init`, `agent-go`, etc.**
  The installer previously dropped only the PowerShell shims
  (`agent-init.ps1`), which Git Bash cannot execute directly. Now
  also drops a bash shim alongside, on every platform. On Windows
  the bash shim delegates to the PowerShell shim so users get the
  platform-native python resolution (the Microsoft Store App
  Execution Alias can hijack a bare `python` call from non-MSYS
  shells). On unix the bash shim is the same as before.

### Added
- **`lavish-axi` is now in the dependency table** and installable via
  `agent-init --bootstrap=lavish-axi` (or `--bootstrap=all`). The
  README and `tools/lavish-axi.md` both claimed this command worked
  pre-fix; it didn't. The entry uses `npm install -g lavish-axi`
  and is kept out of `DEFAULT_BOOTSTRAP_SET` so the default install
  stays focused on the runtime toolchain. Verified on Windows:
  installs `kunchenguid/lavish-axi v0.1.36` and drops a working
  `lavish-axi` binary at `%APPDATA%\npm\lavish-axi`.

### Changed
- **`tools/lavish-axi.md` integration section**: previously claimed
  `agent-init --bootstrap=lavish-axi` runs the `npx skills add`
  step. The workbench installs the npm binary, not the agent
  skill. The new text matches the actual install command.
- **Real install for no-mistakes and treehouse**: replaced the
  fictional `irm ... | iex` URLs in `bootstrap.py` with a
  `_install_from_github_release` helper that downloads the latest
  release asset from the kunchenguid GitHub repos, extracts the
  binary, and places it in `~/.local/bin/`. Verified end-to-end on
  Windows: `no-mistakes v1.31.2` and `treehouse v2.0.0` both install
  and run.
- **`agent-overnight`** — gnhf wrapper with safe defaults. Adds
  `--worktree` (isolated branch), `--max-iterations 50`,
  `--max-tokens 100000`, and a preflight check that refuses to run
  on a dirty repo. Supports `--task-file <path>` so the prompt can
  live in version control. Dry-run mode shows the exact gnhf command
  that would be run. Wired into the dispatcher, the bash and
  PowerShell shims, and the installer's `HELPERS` list.
- **`tools/kunchenguid.md`** — documents how the three kunchenguid
  companion tools (no-mistakes, treehouse, gnhf) integrate with
  the workbench, the typical flows, and what the workbench does
  NOT auto-do for you.
- **`agent-fleet` treehouse backend verified end-to-end**: the
  earlier `treehouse get --lease --label` call used the wrong flag
  (the real one is `--lease-holder`); fixed and verified: a 2-agent
  fleet leases 2 worktrees from the pool and the JSON report
  contains the right paths.
- **`agent-go`** — the one-liner cold-machine bootstrap. Paste
  `iex (irm …/install.ps1)` on a fresh Windows box, or
  `curl -fsSL …/install.sh | sh` on macOS/Linux/WSL, and you end up
  with the full toolkit (helpers on PATH, claude, herdr, firstmate,
  no-mistakes, treehouse, gnhf, ollama, wezterm all installed) and
  herdr started in the background. Then `agent-go` from inside any
  repo assembles the global rules into a system prompt and launches
  `claude` in a herdr pane (or in the current shell with `--no-herdr`).
  - `agent-go --print-cmd` prints the one-liner for docs.
  - `agent-go --print-prompt` prints the assembled prompt to stdout.
  - `agent-go --no-bootstrap` skips the install step.
  - `agent-go --task {code,review,architecture,documentation,general}`
    layers in the matching task prompt.
- **Top-level `install.ps1` and `install.sh`** that the one-liner
  fetches. Clones the repo into `~/.agent-workbench/`, runs
  `agent-init --bootstrap=all`, adds `~/.local/bin` to the user PATH
  (HKCU on Windows, `~/.bashrc` + `~/.zshrc` on unix; no admin needed),
  and prints the next step.
- **Auto-install of external dependencies** via the new `agent-bootstrap` command
  and `agent-init --bootstrap` flag. Defaults: herdr, firstmate, no-mistakes,
  treehouse. Supports `--bootstrap=<list>`, `--all`, `--no-bootstrap`, `--no-curl`,
  and `--json` for machine-readable output.
- **`agent-fleet N`** — multi-agent spawner that creates N isolated worktrees
  and launches N Claude agents in parallel. Backends: `herdr` (default),
  `treehouse` (fallback), `none` (works without any orchestrator). Supports
  `--wait` to block until all agents finish, `--worktree yes|no|auto`, and
  `--json` for machine-readable spawn reports.
- **`agent_doctor.py`** — Python module wrapping `firstmate doctor`,
  `firstmate build`, and `no-mistakes check --all`. Wired into `agent_check`
  so a single `agent-check` run covers project structure, toolchain health,
  and pre-push validation.
- **`agent-claude` now uses the real Claude Code CLI** (`claude` on PATH)
  instead of the fictional `ollama launch claude` subcommand. Supports
  `--backend auto|herdr|claude|ollama|none` and `--worktree auto|yes|no`.
  When herdr is installed, `agent-claude` runs the agent in an isolated
  herdr pane on a fresh worktree.
- **`tools/herdr.md`** — the doc that was missing. Covers install on
  Windows / macOS / Linux, the `herdr integration install claude` step,
  and the CLI surface `agent-fleet` and `agent-claude` rely on.
- **Honest `tools/*.md`** — rewrote `firstmate.md`, `no-mistakes.md`,
  `lavish-axi.md`, `gnhf.md`, and `treehouse.md` to point at the real
  GitHub repos (`github.com/kunchenguid/*`) instead of the fictional
  `*.dev` URLs the original docs cited. Added install method per platform
  and the `agent-workbench` integration notes.

### Changed
- **`agent-init` now writes a marker file** (`~/.local/bin/agent-workbench-home`)
  next to the installed shims so the PowerShell wrappers can find the toolkit
  root when run from `~/.local/bin/` (they used to break with a relative-path
  bug — `..\..` lands at `~/.local/` instead of the toolkit root).
- **All PowerShell shims** now use a four-step toolkit-root resolution:
  `AGENT_WORKBENCH_HOME` env var → marker file → walk-up → legacy `..\..`.
- **`agent_test` defaults to `firstmate test`** when a `firstmate.toml` is
  in the repo root AND firstmate is detected (binary on PATH or
  `~/firstmate/AGENTS.md`). `agent-test --firstmate` forces it;
  `--no-firstmate` skips it.
- **`agent_check` now runs `firstmate doctor` / `firstmate build` and
  `no-mistakes check --all`** when those tools are installed, surfacing
  their output as `[ok]/[info]/[warn]/[err]` lines. `agent-check
  --no-firstmate` / `--no-no-mistakes` skip them.
- **`install.py`'s `HELPERS` list** now includes `agent-bootstrap` and
  `agent-fleet` so `agent-init` installs the full set of 8 helpers.

### Fixed
- **`agent-check` no-mistakes invocation**: was calling the
  non-existent `no-mistakes check --all` subcommand. Replaced with
  the real `no-mistakes doctor` (system health) and `no-mistakes
  status` (current run, only when the gate is initialized). Doctor
  output is now surfaced as `[ok]/[warn]/[info]` lines in
  `agent-check`.
- **`agent-fleet` treehouse lease flag**: was passing
  `--label agent-<name>` to `treehouse get --lease`; the real flag
  is `--lease-holder`. Fixed and verified.
- **`agent-claude` and `agent-fleet` no longer shell out to `cat`**:
  the herdr backend's `claude --append-system-prompt "@$(cat
  <file>)"` worked on bash but failed on Windows (and even in bash
  on Windows, `cat` isn't on PATH inside the herdr spawn). Reads
  the prompt into a Python string and passes it directly.
- **`agent-claude` herdr backend no longer uses `$(cat <file>)`** to
  pass the system prompt to `claude` (that breaks on Windows where
  `cat` is not on PATH inside the herdr spawn). It now reads the
  prompt into a Python string and passes it via the standard
  `--append-system-prompt <body>` flag.
- **`build_prompt.py` no longer self-includes its own outputs**:
  `.agent/SYSTEM_PROMPT.md` and `.agent/SYSTEM_PROMPT.fleet-N.md` are
  produced by the workbench itself, so loading them back into a future
  prompt assembly caused a quadratic blow-up (every new prompt included
  every previous prompt). The collector now skips those files via
  `_SELF_PRODUCED_NAMES` and `_SELF_PRODUCED_GLOBS`. Verified: a fresh
  prompt is 6.3 KB, re-runs are stable, and fleet-N prompts are 6.7 KB.
- **`agent-claude` no longer calls the fictional `ollama launch claude`**
  subcommand. It now uses `claude` (the real Claude Code CLI), `ollama run`,
  or prints a paste-ready summary.
- **Pre-existing PowerShell relative-path bug**: when a shim is run from
  its installed location (`~/.local/bin/agent-*.ps1`), the toolkit root
  resolution used to fail because `..\..` doesn't reach the toolkit. Fixed
  via the marker-file approach described above.

### Added
- **`--runtime ollama` is now Claude-Code-via-ollama by default.**
  The `ollama` runtime no longer runs `ollama run <model>` (which
  drops the user into a chat REPL with `>>> Send a message`).
  It runs `claude --model <model>` with
  `ANTHROPIC_BASE_URL=http://localhost:11434` and
  `ANTHROPIC_AUTH_TOKEN=ollama`, pointing Claude Code at ollama's
  OpenAI-compatible HTTP endpoint. The same coding-agent UX, the
  model is local. A user without Anthropic login can now run
  `agent-go --task code --runtime ollama --model minimax-m3:cloud`
  and get a Claude-Code-like coding agent inside Herdr, backed by
  the selected Ollama model.
- **New runtime `--runtime ollama-chat`** for the plain
  `ollama run <model>` chat REPL. This is the opt-in path, not
  the default for `agent-go --task code`. The runtime resolves
  its model from `[ollama_chat]` in the config (with the
  `[ollama]` section as a fallback for legacy configs).
- **`[ollama].mode` config field** lets users pick the runtime
  shape at the config layer. `mode = "claude"` (default) is the
  claude-via-ollama flow described above; `mode = "chat"` is the
  plain `ollama run` REPL. The mode can also be overridden via
  the `AGENT_OLLAMA_MODE` env var.
- **`agent-go --setup`** — an interactive first-run flow that
  writes `~/.agent-workbench/config.toml`. If `lavish-axi` is on
  PATH, the setup defers to it (treated as a black box — the
  user saves the page and we read the file back). Otherwise, a
  short terminal prompt walks the user through runtime, model,
  mode (for ollama), backend, and UI choices. The written file
  is self-documenting (commented) so the user can read and edit
  it without re-running `--setup`. Existing files are asked
  before overwriting. The flow is optional — every flag works
  without it.
- **herdr `agent_name_taken` auto-recovery** in `agent-go`,
  `agent-claude`, and `agent-fleet`. If herdr returns
  `agent_name_taken` (or any "is already used" / "name already
  in use" marker), the spawn retries with `primary-2`,
  `primary-3`, ..., `primary-5`, then `primary-<6-hex>` short
  ids. Up to 8 attempts (`agent-go` / `agent-claude`) or 4
  attempts (`agent-fleet`); on exhaustion the spawn falls back
  to the direct runner with a clear message.
- **Pre-launch output block (7 lines)** printed before the
  spawn so the user can see what is about to run:
  ```
  agent-workbench: runtime:      ollama
  agent-workbench: runtime mode: claude-via-ollama
  agent-workbench: model:        minimax-m3:cloud
  agent-workbench: backend:      herdr
  agent-workbench: command:      claude --model minimax-m3:cloud
  agent-workbench: agent:        primary-2
  agent-workbench: cwd:          C:\path\to\repo
  ```
  The first three lines (runtime / mode / model) are printed
  before any spawn attempt; the rest are printed after a
  successful herdr spawn (or on fallback).
- **`[backend]` and `[ui]` config sections.** `[backend] default`
  picks the orchestrator (herdr / treehouse / none); `[ui] setup`
  picks the setup UI (lavish-axi / terminal). Both are read by
  `agent-go --setup` and by the backend resolution layer.
- **`utils.unique_agent_name(base, attempt)`** — deterministic
  unique agent names: `base` on attempt 0, `base-2..base-5` on
  attempts 1..4, `base-<6-hex>` short id on attempts 5+.
  `utils.is_agent_name_taken_error()` is the matching
  case-insensitive substring probe. Both helpers are shared
  by all three herdr-using commands.

### Changed
- **`scripts/python/runtime.py` runtime taxonomy** is now
  `(claude, ollama, ollama-chat, openai-compatible)`. The
  `Runtime` dataclass gained a `mode: str = "default"` field;
  `Runtime.is_ollama_chat()` and the `_runtime_mode_label()`
  helper expose the resolved mode to the spawn layer. The
  `_build_ollama_args()` helper was renamed
  `_build_ollama_claude_args()` and now returns
  `["claude", "--model", m]` with the ollama env overrides;
  `_build_ollama_chat_args()` is the new opt-in chat REPL path.
- **`agent-claude` and `agent-fleet` now retry on herdr
  `agent_name_taken`** (defensive — covers the case where a
  previous `agent-go` session left a stale `primary` on the
  server). Same retry shape as `agent-go` (8 attempts in
  `agent-claude`, 4 per agent in `agent-fleet`).

### Out of scope (deferred to a future round)
- Replacing the per-script PowerShell wrappers with a single delegating
  dispatcher (the bash vs PS divergence in the original repo).
- Wiring `gnhf` and `lavish-axi` into dedicated `agent-workbench` commands
  (the bootstrap step installs them; no orchestration yet).
- VS Code task integration (mentioned in the original roadmap).

## [0.1.0] - 2026-07-05

### Added
- First public release.
