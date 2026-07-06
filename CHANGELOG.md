# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

### Out of scope (deferred to a future round)
- Replacing the per-script PowerShell wrappers with a single delegating
  dispatcher (the bash vs PS divergence in the original repo).
- Wiring `gnhf` and `lavish-axi` into dedicated `agent-workbench` commands
  (the bootstrap step installs them; no orchestration yet).
- VS Code task integration (mentioned in the original roadmap).

## [0.1.0] - 2026-07-05

### Added
- First public release.
