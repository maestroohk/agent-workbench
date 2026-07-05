# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
