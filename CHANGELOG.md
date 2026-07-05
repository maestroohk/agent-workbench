# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
