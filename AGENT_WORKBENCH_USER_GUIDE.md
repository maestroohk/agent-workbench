# agent-workbench — user guide

> A practical, end-to-end manual for `agent-workbench`. This document is
> for a developer who has never used the toolkit before. After reading
> it you should be able to install the workbench on a fresh machine,
> open any repository, run an agent with the correct global context,
> spawn parallel agents, run an overnight loop, and recover from the
> failure modes that have actually happened in the wild.

---

## Table of contents

1. [High-level architecture](#1-high-level-architecture)
2. [Every command explained](#2-every-command-explained)
   - 2.11 [Runtimes and providers (Claude / Ollama / OpenAI-compatible)](#211-runtimes-and-providers-claude--ollama--openai-compatible)
3. [Every integrated tool explained](#3-every-integrated-tool-explained)
4. [Prompt generation: how the system prompt is built](#4-prompt-generation-how-the-system-prompt-is-built)
5. [End-to-end workflows](#5-end-to-end-workflows)
6. [TeamTasksBoard walkthrough: from `dotnet new blazor` to working app](#6-teamtasksboard-walkthrough-from-dotnet-new-blazor-to-working-app)
7. [Windows-specific guide](#7-windows-specific-guide)
8. [Troubleshooting](#8-troubleshooting)
9. [Best practices](#9-best-practices)
10. [Developer reference](#10-developer-reference)

---

## 1. High-level architecture

`agent-workbench` is a thin orchestrator. The actual work — model
inference, worktree management, validation, overnight loops — happens
in **upstream tools** that the workbench installs and drives. The
workbench's job is to:

- put those tools on your `PATH` and wire them up,
- assemble the system prompt the model sees,
- pick the right runner (model + worktree strategy) for the task,
- print clear diagnostics when something goes wrong.

### 1.1 Information flow

```
   ┌─────────────────────────────────────────────────────────────┐
   │                        Your machine                          │
   │                                                             │
   │   ┌──────────────┐    ┌────────────────────────────────┐    │
   │   │ ~/.local/bin │    │  Repository (the project)      │    │
   │   │  agent-go    │    │  ├── AGENTS.project.md         │    │
   │   │  agent-scan  │◀──▶│  ├── .agent/                   │    │
   │   │  agent-...   │    │  │   ├── repo-summary.md       │    │
   │   └──────┬───────┘    │  │   ├── architecture.md       │    │
   │          │            │  │   ├── build.md              │    │
   │          ▼            │  │   ├── commands.md           │    │
   │   ┌──────────────┐    │  │   ├── dependencies.md       │    │
   │   │ dispatch.py  │    │  │   └── coding-style.md       │    │
   │   │  (verifier)  │    │  └── src/                      │    │
   │   └──────┬───────┘    └────────────────────────────────┘    │
   │          │                                                 │
   │          ▼                                                 │
   │   ┌──────────────────────────────────────────────────┐    │
   │   │   agent-go / agent-claude / agent-fleet          │    │
   │   │                                                  │    │
   │   │  1. assemble prompt                              │    │
   │   │     ├── AGENTS.md            (workbench global)  │    │
   │   │     ├── prompts/<task>.md    (agent role)        │    │
   │   │     ├── profiles/<stack>.md  (tech-specific)     │    │
   │   │     ├── AGENTS.project.md    (your project)      │    │
   │   │     └── .agent/*.md          (auto-generated)    │    │
   │   │                                                  │    │
   │   │  2. start herdr server (background)              │    │
   │   │  3. spawn runner                                 │    │
   │   │     ├── herdr agent start  (worktree + pane)     │    │
   │   │     ├── claude --append-system-prompt ...        │    │
   │   │     └── ollama run <model>   (fallback)          │    │
   │   └─────────────────────────┬────────────────────────┘    │
   └─────────────────────────────┼──────────────────────────────┘
                                 ▼
              ┌─────────────────────────────────────┐
              │  Model runtime (claude / ollama)    │
              │   ↑          ↑           ↑          │
              │   │          │           │          │
              │  herdr    firstmate    gnhf         │
              │  (pane)   (multi-agent) (overnight) │
              └─────────────────────────────────────┘
                                 │
                                 ▼
              ┌─────────────────────────────────────┐
              │  no-mistakes (validation gate)      │
              │   - no-mistakes doctor              │
              │   - no-mistakes status              │
              └─────────────────────────────────────┘
```

### 1.2 The four layers

The workbench is intentionally layered; each layer can be replaced
without touching the others.

| Layer | What it is | Replaceable? |
| --- | --- | --- |
| **Shell shims** | `agent-go`, `agent-scan`, etc. PowerShell `.ps1` and bash. | yes — write your own launcher that calls `dispatch.py` |
| **Python business logic** | `scripts/python/*.py` — single source of truth. | yes — fork and modify |
| **External tools** | `claude`, `ollama`, `herdr`, `firstmate`, `treehouse`, `no-mistakes`, `gnhf`, `lavish-axi`, `wezterm` | yes — these are roles; the tools filling them can change |
| **The model** | `claude` (default), `ollama` (local fallback) | yes — override with `--model` or `AGENT_MODEL` env var |

### 1.3 The 9-step session workflow

After a clean install, every session follows this loop. Not every step
runs in every session — steps 4, 5, 6, and 9 are optional or
context-dependent.

1. **Bootstrap / install prerequisites.** `agent-init --bootstrap` installs the runtime toolchain.
2. **Verify PATH / tool availability** without silently editing shell profiles.
3. **Scan the target repo** with `agent-scan` to generate `.agent/` context.
4. **Create a visual plan** with `lavish-axi` when the task is complex or UI-related.
5. **Use `firstmate` to delegate work** to specialized agents (the orchestrator role).
6. **Use `treehouse` for isolated worktrees** for agent tasks.
7. **Run project tests / checks** with `agent-test`.
8. **Run `no-mistakes` as the final validation gate** (called by `agent-check`).
9. **Produce a concise final report** — preferably with `lavish-axi` for visual review.

### 1.4 The slim default vs. the full table

The default install is the **slim runtime set** — only the tools you
hit on the hot path:

| Tool | In default? | Why |
| --- | --- | --- |
| `claude` | yes | The model runner |
| `herdr` | yes | The pane + worktree backend |
| `firstmate` | yes | The orchestrator harness |
| `no-mistakes` | yes | The pre-push validation gate |
| `ollama` | yes | Fallback when `claude` is unavailable |
| `treehouse` | opt-in | Multi-agent worktree pool (`agent-fleet --backend treehouse`) |
| `lavish-axi` | opt-in | Visual collaboration tool |
| `gnhf` | opt-in | Overnight autonomous runner |
| `wezterm` | opt-in | Optional GPU terminal |

`agent-init --bootstrap=all` installs the full table. `agent-init --bootstrap=treehouse` installs only that one. `agent-init --no-bootstrap` installs nothing.

---

## 2. Every command explained

The workbench ships 10 user-facing commands. Each one is a thin
shell wrapper that calls into a Python module via `dispatch.py`. The
wrappers **never** parse arguments — all argument parsing happens in
the Python module, which is the single source of truth for each
command's interface.

### 2.1 `agent-init`

**What it does:** Install or update the workbench on the current machine. Creates `~/.agent-workbench/`, symlinks (or copies, on Windows without privileges) the 10 helper scripts into `~/.local/bin/`, writes a marker file so the helpers can find the toolkit root, and optionally bootstraps the runtime toolchain.

```bash
# First-time install with the slim default toolchain
agent-init

# Update (re-link helpers, re-bootstrap defaults)
agent-init --force

# Install everything in the dependency table
agent-init --bootstrap=all

# Install only specific tools
agent-init --bootstrap=claude,herdr,firstmate

# Skip the tool install — only install the workbench's own helpers
agent-init --no-bootstrap
```

| Flag | Effect |
| --- | --- |
| `--force` | Overwrite existing helpers in `~/.local/bin/`. |
| `--bootstrap=LIST` | Comma-separated list of tools to install. Pass `all` for the full table. Default: `herdr,firstmate,no-mistakes`. |
| `--no-bootstrap` | Only install the workbench's own helpers; skip the external tools. |
| `--no-curl` | Skip install methods that pipe a remote shell (winget/choco/brew/git only). |
| `--print-platform` | Print the detected platform (`linux`, `darwin`, `windows`, `wsl`) and exit. |

**What it does NOT do:**

- Modify the system PATH. The caller is responsible for adding `~/.local/bin` to their user PATH. The installer prints the exact line to add.
- Touch anything outside `~/.agent-workbench/` and `~/.local/bin/`.
- Modify `~/.bashrc`, `~/.zshrc`, PowerShell profile, or HKCU PATH without explicit consent.

### 2.2 `agent-bootstrap`

**What it does:** Install or check the external tools (the workbench's dependencies). Same dependency table as `agent-init --bootstrap`, but standalone — useful when the workbench itself is already installed and you only want to add or check a tool.

```bash
# Install the slim default set
agent-bootstrap

# Check status of every dependency without installing
agent-bootstrap --check

# Install a specific tool
agent-bootstrap --only=herdr

# Install everything
agent-bootstrap --all

# JSON output for scripting
agent-bootstrap --check --json
```

| Flag | Effect |
| --- | --- |
| `--only=LIST` | Comma-separated list. Default: `herdr,firstmate,no-mistakes`. |
| `--all` | Install every dependency in the table. |
| `--check` | Only report status; do not install. |
| `--no-curl` | Skip methods that pipe a remote shell. |
| `--json` | Emit machine-readable JSON. |

### 2.3 `agent-scan`

**What it does:** Scan the current repository and write six short summaries to `.agent/`. Each summary is intentionally short — these are loaded into the model prompt, not read end-to-end by a human.

| File | Contents |
| --- | --- |
| `.agent/repo-summary.md` | Top-level directories, top-level files (first 50), language breakdown by lines of code. |
| `.agent/architecture.md` | Module descriptions (from each subdir's `README.md` first line), entry points, detected stack. |
| `.agent/build.md` | Package managers, container files, CI/CD workflows. |
| `.agent/commands.md` | Inferred build/test commands for the detected stack. |
| `.agent/dependencies.md` | Direct dependencies from `package.json` or `pyproject.toml`. |
| `.agent/coding-style.md` | Linter / formatter / `Directory.Build.props` detection. |

```bash
# Scan the current directory (auto-detects the repo root)
agent-scan

# Scan a specific repo
agent-scan --repo C:\path\to\repo
```

When to re-run: after adding a new top-level directory, after major dependency changes, or after the stack changes (e.g. you add a `Dockerfile` or a new `package.json`).

### 2.4 `agent-check`

**What it does:** Lightweight validation of the repository. Checks:

- **Stack detection** — does any technology profile match? Prints each match with the evidence.
- **`.agent/` directory** — does it exist? Are all six summary files present? If missing, the message is "run `agent-scan` to generate it".
- **Project instructions** — does `AGENTS.project.md` or `CLAUDE.md` exist?
- **No committed secrets** — surfaces `.env`, `credentials.json`, `service-account.json` if present.
- **`firstmate` health** — if installed, calls `firstmate` (via the shim) to surface the harness's preflight output. Reports the harness install path and most recent commit.
- **`no-mistakes` health** — if installed, calls `no-mistakes doctor` and `no-mistakes status` and surfaces the output.

```bash
# Run the full check
agent-check

# Skip the firstmate integration
agent-check --no-firstmate

# Skip the no-mistakes integration
agent-check --no-no-mistakes
```

Output is one finding per line, prefixed with `[ok]`, `[info]`, `[warn]`, or `[err]`. Exit code is 0 if no `[err]` lines, 1 otherwise.

### 2.5 `agent-review`

**What it does:** Build the system prompt and print it to stdout. This is the read-only path — nothing is installed, no model is launched, no server is started.

```bash
# Build the review-agent prompt (default)
agent-review

# Build the coding-agent prompt
agent-review --task code

# Save the prompt to a file
agent-review --output ./my-prompt.md

# See which files were loaded
agent-review --print-loaded
```

| Flag | Effect |
| --- | --- |
| `--task` | Which task-specific agent prompt to layer in. Choices: `code`, `review`, `architecture`, `documentation`, `general`. Default: `review`. |
| `--output PATH` | Write the prompt to this file instead of stdout. |
| `--show-files` / `--no-show-files` | Print or suppress the list of files that contributed. Default: on. |
| `task_text` | Optional positional argument — appended as a `## Task` section. |

### 2.6 `agent-go`

**What it does:** The one-liner that takes you from a clean machine to a working agent session.

In order:

1. **Assemble the prompt** (`AGENTS.md` → task prompt → detected profiles → project rules → `.agent/` summaries). Done up-front so the read-only paths work without touching the network.
2. **Bootstrap missing tools** (unless `--no-bootstrap` or `--print-prompt`/`--print-cmd`).
3. **Ensure `~/.local/bin` is on PATH** for the current process.
4. **Write the prompt** to `<repo>/.agent/SYSTEM_PROMPT.md` (where Claude Code auto-loads it).
5. **Start the herdr server** in the background.
6. **Launch the model** — `herdr agent start -- <claude>` (preferred) or `claude` directly or `ollama run <model>` (fallback).

```bash
# The documented flow
agent-go --task code

# Read-only: just print the prompt
agent-go --task code --print-prompt

# Read-only: print the one-liner to give a colleague
agent-go --print-cmd

# Skip herdr — run claude in the current PowerShell
agent-go --task code --no-herdr

# Use a different model
agent-go --model minimax-m3:cloud

# Don't install anything
agent-go --task code --no-bootstrap

# Append a specific task description
agent-go --task code "Fix the race condition in TaskBoardService.cs"
```

| Flag | Effect |
| --- | --- |
| `--task` | Which task-specific agent prompt. Choices: `code`, `review`, `architecture`, `documentation`, `general`. |
| `--runtime` | Which model runner to use. Choices: `claude` (Anthropic Claude Code, default), `ollama` (local Ollama), `openai-compatible` (Claude Code pointed at a custom `ANTHROPIC_BASE_URL`). See [§2.11](#211-runtimes-and-providers-claude--ollama--openai-compatible) for the full story. |
| `--model` | Override the model. Default per runtime: `opus` for `claude`, `minimax-m3:cloud` for `ollama` and `openai-compatible`. Also accepts `$AGENT_MODEL` or `~/.agent-workbench/config.toml`. |
| `--base-url` | (`openai-compatible`) The Anthropic-protocol base URL (e.g. `http://localhost:1234/v1` for LM Studio). |
| `--api-key-env` | (`openai-compatible`) Name of the env var holding the API key (e.g. `OPENAI_API_KEY`). Value is read at spawn time. |
| `--bootstrap=LIST` | Comma-separated list of tools to install. Default: `claude,herdr,firstmate,no-mistakes,ollama`. |
| `--no-bootstrap` | Skip the install step. |
| `--no-herdr` | Run the model in the current shell, not in a herdr pane. |
| `--no-attach` | Start the herdr agent but do not auto-attach the terminal to its pane. The instruction block (`herdr agent attach primary`) is printed instead. Useful for CI / scripted use. |
| `--no-curl` | Skip install methods that pipe a remote shell. |
| `--print-cmd` | Print the one-liner for a fresh machine and exit. Now also prints the resolved runtime + model so docs reviewers can see what would be used. |
| `--print-prompt` | Print the assembled prompt to stdout and exit. No install, no herdr, no model. The resolved runtime + model + base_url (for `openai-compatible`) is printed at the top of stderr. |
| `task_text` | Optional positional argument — appended to the prompt. |

**Opting out of auto-attach globally:** Set `AGENT_GO_NO_AUTO_ATTACH=1` in the environment. The flag and the env var have the same effect; the flag is for one-off use, the env var for scripts. Auto-attach is also disabled automatically when stdout is not a TTY (e.g. in CI).

**Why `agent-go` is the right entry point:** It centralises the steps that *every* session needs (prompt assembly, tool probe, prompt write, model launch) and exposes the same flags regardless of whether the user wants a one-shot read (`--print-prompt`) or a full herdr-pane session (no flags).

### 2.7 `agent-claude`

**What it does:** The model runner — assemble the prompt and launch the model. `agent-go` is the more user-friendly wrapper; `agent-claude` exposes the backend choice directly.

```bash
# Default: herdr-isolated claude if available
agent-claude

# Force direct claude (no herdr)
agent-claude --backend=claude

# Force ollama
agent-claude --backend=ollama

# Just write the prompt and exit
agent-claude --write-only

# Just print the prompt
agent-claude --show-prompt
```

| Flag | Effect |
| --- | --- |
| `--backend` | Orchestrator: `auto` (default), `herdr`, `claude`, `ollama`, `none`. Picks how the agent is launched (herdr pane vs. direct shell vs. nothing). |
| `--runtime` | Model runner: `claude` (default), `ollama`, `openai-compatible`. Picks which binary talks to the model. See [§2.11](#211-runtimes-and-providers-claude--ollama--openai-compatible). |
| `--worktree` | `auto` (default), `yes`, `no`. With `--backend=herdr`: spawn the agent on a fresh worktree. |
| `--show-prompt` | Print the prompt and exit. |
| `--write-only` | Write the prompt to `.agent/SYSTEM_PROMPT.md` and exit. |
| `--print-loaded` | Print the list of files that contributed to the prompt. |
| `--model` | Override the model. Default per runtime: `opus` for `claude`, `minimax-m3:cloud` for `ollama` and `openai-compatible`. |
| `--base-url` | (`--runtime=openai-compatible`) The Anthropic-protocol base URL. |
| `--api-key-env` | (`--runtime=openai-compatible`) Name of the env var holding the API key. |
| `--task` | Which task-specific agent prompt. |

### 2.8 `agent-test`

**What it does:** Run the project's test suite. Detects the test runner from the repo and dispatches.

| Detection | Command |
| --- | --- |
| `firstmate.toml` present and `firstmate` installed | `firstmate test` |
| `*.sln` present | `dotnet test -c Release` |
| `pom.xml` present | `mvn -B test` |
| `build.gradle` present | `./gradlew test` (or `gradle test`) |
| `package.json` with `pnpm` | `pnpm test` |
| `package.json` with `yarn` | `yarn test` |
| `package.json` with `bun` | `bun test` |
| `package.json` (no specific PM) | `npm test` |
| `poetry.lock` | `poetry run pytest` |
| `uv.lock` | `uv run pytest` |
| `Pipfile.lock` | `pipenv run pytest` |
| `pyproject.toml` / `pytest.ini` / `tests/` | `pytest` |

```bash
# Run the detected test suite
agent-test

# Print the command without running it
agent-test --dry-run

# Force firstmate even when the auto-detect is uncertain
agent-test --firstmate
```

### 2.9 `agent-fleet`

**What it does:** Spawn N Claude agents in parallel, each in an isolated context so they do not pollute the user's main checkout.

```bash
# Spawn 3 agents in herdr panes (default)
agent-fleet 3 --task code

# Wait for all of them to finish
agent-fleet 3 --task code --wait

# Use treehouse-leased worktrees
agent-fleet 3 --task code --backend treehouse

# No isolation (for testing only)
agent-fleet 3 --task code --backend none

# 10-minute per-agent timeout
agent-fleet 3 --task code --wait --timeout 600000
```

| Flag | Effect |
| --- | --- |
| `count` (positional) | Number of agents to spawn. Required. |
| `--task` | Which task-specific agent prompt for all agents. |
| `--model` | Override the model for all agents. Default per runtime: `opus` for `claude`, `minimax-m3:cloud` for `ollama` and `openai-compatible`. |
| `--runtime` | Model runner: `claude` (default), `ollama`, `openai-compatible`. The herdr and treehouse backends require `--runtime=claude`; for other runtimes the fleet falls back to `--backend=none`. See [§2.11](#211-runtimes-and-providers-claude--ollama--openai-compatible). |
| `--base-url` | (`--runtime=openai-compatible`) The Anthropic-protocol base URL. |
| `--api-key-env` | (`--runtime=openai-compatible`) Name of the env var holding the API key. |
| `--backend` | `auto` (default), `herdr`, `treehouse`, `none`. |
| `--worktree` | `auto`, `yes`, `no`. Whether each agent gets its own worktree. |
| `--wait` | Block until all agents report `done`. |
| `--timeout` | Per-agent wait timeout in milliseconds. Default: 600000 (10 min). |
| `--json` | Emit machine-readable JSON. |
| `task_text` | Optional positional argument — appended to every agent's prompt. |

**The three backends:**

- **`herdr` (default when available).** Each agent gets a fresh worktree (`herdr worktree create`) and a new pane (`herdr agent start --split right --no-focus`). The herdr server keeps the agents alive in the background; the user can `herdr agent attach <name>` to follow one, or `herdr agent wait <name> --status done` to block.
- **`treehouse`.** Leases N pre-warmed worktrees from the pool via `treehouse get --lease`. Best for cheap, reusable isolation; worktrees return to the pool when the agent exits.
- **`none`.** Writes N per-agent prompts to `.agent/SYSTEM_PROMPT.fleet-N.md` and tries to spawn N `claude` processes in the same checkout. Use only for testing — agents will collide on the working tree.

### 2.10 `agent-overnight`

**What it does:** Wrap `gnhf` (the overnight loop driver) with safe defaults. Each successful iteration is a separate commit; aborts on `--max-iterations`, `--max-tokens`, or the agent reporting `--stop-when`.

```bash
# Run with a positional task
agent-overnight "Fix all typecheck warnings in src/"

# Read the task from a file
agent-overnight --task-file overnight-task.md

# Use Codex instead of Claude
agent-overnight --agent codex

# Push the gnhf branch after each successful iteration
agent-overnight --task-file overnight-task.md --push

# Run even on a dirty repo (not recommended)
agent-overnight --allow-dirty "fix warnings"

# Just print the gnhf command, don't run it
agent-overnight --dry-run --task-file overnight-task.md
```

| Flag | Effect |
| --- | --- |
| `--task-file PATH` | Path to a file holding the task description. |
| `--agent` | Which agent gnhf should drive. Default: `claude`. |
| `--max-iterations` | Abort after N iterations. Default: 50. |
| `--max-tokens` | Abort after N tokens. Default: 100000. |
| `--stop-when MARKER` | Optional gnhf `--stop-when` marker. |
| `--no-worktree` | Run in the current checkout (NOT recommended). |
| `--current-branch` | Use the current branch instead of `gnhf/<slug>`. |
| `--push` | Push the gnhf branch after each successful iteration. |
| `--allow-dirty` | Skip the preflight check that refuses to run on a dirty repo. |
| `--dry-run` | Print the gnhf command and exit. |

**The preflight:** By default, `agent-overnight` refuses to run on a dirty repo (`git status --porcelain` returns any output). This is to prevent your WIP from being mixed into the gnhf commit log. Pass `--allow-dirty` to override (not recommended).

**gnhf on Windows:** As of 2026-07-06, `gnhf` ships no Windows release. The default `agent-go` flow does not use gnhf; only `agent-overnight` does. The default bootstrap does not pull gnhf on any platform, so a clean install does not see the "no asset matching" error.

---

### 2.11 Runtimes and providers (Claude / Ollama / OpenAI-compatible)

`agent-go` used to assume Claude Code was the only interactive model runner. A user without an Anthropic subscription had no documented path to a working session — they would type `agent-go --task code` and end up in a herdr pane that said `Not logged in · Run /login`. The runtime layer fixes this: there are now three first-class **runtimes** the user can pick, and the workbench detects the "Claude not logged in" case before dropping the user into a broken pane.

#### The three runtimes

| Runtime | Binary | Default model | Login required? | When to use |
| --- | --- | --- | --- | --- |
| `claude` | `claude` (Claude Code) | `opus` | yes | Default. Use if you have an Anthropic subscription or an `ANTHROPIC_API_KEY`. |
| `ollama` | `ollama` | `minimax-m3:cloud` | no | Use if you want local inference. No Anthropic account required. |
| `openai-compatible` | `claude` (Claude Code) | `minimax-m3:cloud` | depends on provider | Use if you have a local LM Studio, vLLM, LiteLLM proxy, or any other provider that speaks the Anthropic wire protocol through `ANTHROPIC_BASE_URL`. |

> **Important design point:** `minimax-m3:cloud` is no longer hardcoded as a Claude model. The default is **runtime-specific**: `opus` for `claude`, `minimax-m3:cloud` for `ollama` and `openai-compatible`. Override per command with `--model <name>`.

#### Resolution order

For both the runtime name and the model name, the workbench uses the same four-layer order:

```
CLI flag   >   env var   >   config file   >   default
--runtime      AGENT_RUNTIME   ~/.agent-workbench/config.toml   DEFAULT_RUNTIME ("claude")
--model        AGENT_MODEL     [runtime].model / [runtime].model  DEFAULT_MODELS[runtime]
```

Examples:

```bash
# Pick the runtime for one command
agent-go --task code --runtime ollama --model minimax-m3:cloud

# Set the runtime for a whole session
AGENT_RUNTIME=ollama agent-go --task code

# Set the runtime once for a project (in ~/.agent-workbench/config.toml)
# [runtime]
# default = "ollama"
#
# [ollama]
# model = "minimax-m3:cloud"

# Override the model via config
# [claude]
# model = "opus"
```

#### Config file: `~/.agent-workbench/config.toml`

Four sections, all optional:

```toml
[runtime]
default = "ollama"               # or "claude", "openai-compatible"

[claude]
model = "opus"                   # used when --runtime=claude and no --model

[ollama]
model = "minimax-m3:cloud"       # used when --runtime=ollama and no --model

[openai_compatible]
base_url = "http://localhost:1234/v1"
api_key_env = "OPENAI_API_KEY"   # the value of this env var is read at spawn time
model = "minimax-m3:cloud"
```

The legacy top-level `model = "..."` form is honored as a fallback for users who haven't migrated.

#### "Claude Code opened but is not logged in"

When you pick the `claude` runtime and the workbench cannot find any of:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `CLAUDE_CODE_OAUTH_TOKEN`
- `$CLAUDE_CONFIG_DIR/.credentials.json` (or `~/.claude/.credentials.json`)
- `~/.claude.json` (legacy)

…the workbench prints the documented fallback message and exits 0. You do not land in a broken pane:

```
agent-workbench: Claude Code opened but is not logged in.
Run `/login` inside Claude, or use:
  agent-go --task code --runtime ollama --model <model>
  agent-go --task code --runtime openai-compatible --model <model> --base-url <url>
```

#### Per-runtime verify commands

| Runtime | Verify |
| --- | --- |
| `claude` | `claude --version` and `claude /login` (or set `ANTHROPIC_API_KEY`). |
| `ollama` | `ollama --version` and `ollama list` (your model should appear; if not, `ollama pull <model>`). |
| `openai-compatible` | `curl <base-url>/v1/models` (LM Studio / vLLM / LiteLLM should return a JSON list of models). |

#### `--backend` vs `--runtime`

These are orthogonal axes:

- `--backend` (on `agent-claude` and `agent-fleet`) picks the **orchestrator**: how the agent is launched — herdr pane (`herdr`), direct shell (`claude`), no launch (`none`).
- `--runtime` (on `agent-go`, `agent-claude`, `agent-fleet`) picks the **model runner**: which binary talks to the model.

The herdr and treehouse backends require `--runtime=claude` because herdr's `agent start` is hardcoded to call the `claude` CLI via its integration hook. For `ollama` and `openai-compatible`, the workbench falls back to `--backend=none` automatically.

#### Examples

```bash
# Claude Code in a herdr pane (default)
agent-go --task code

# Claude Code in the current shell (no herdr)
agent-go --task code --no-herdr

# Ollama locally
agent-go --task code --runtime ollama --model minimax-m3:cloud

# LM Studio at http://localhost:1234/v1
export OPENAI_API_KEY=lm-studio
agent-go --task code --runtime openai-compatible \
         --base-url http://localhost:1234/v1 \
         --api-key-env OPENAI_API_KEY

# Three agents, all running on Ollama
agent-fleet 3 --task code --runtime ollama --model minimax-m3:cloud

# Same, but pointed at LM Studio
agent-fleet 3 --task code --runtime openai-compatible \
             --base-url http://localhost:1234/v1 --api-key-env OPENAI_API_KEY
```

See [§7 Windows-specific guide](#7-windows-specific-guide) for the per-runtime install + verify steps on Windows.

---

## 3. Every integrated tool explained

The workbench orchestrates nine external tools, each filling a stable
**role**. The roles are stable; the tools that fill them can change.

| Role | Tool | Why it's in the default | Install source |
| --- | --- | --- | --- |
| `agent-runtime` | `herdr` | Multiplexer for panes and worktrees. The default backend for `agent-fleet`. | `https://herdr.dev` |
| `model-runtime` | `claude` | Anthropic Claude Code CLI. The actual agent runtime. | `npm install -g @anthropic-ai/claude-code` |
| `model-runtime` | `ollama` | Local model runtime. Fallback when `claude` is unavailable. | `winget install Ollama.Ollama` / `brew install ollama` / `curl -fsSL https://ollama.com/install.sh \| sh` |
| `orchestrator` | `firstmate` | Per-project command orchestrator harness. | `git clone https://github.com/kunchenguid/firstmate.git ~/firstmate` |
| `validation-gate` | `no-mistakes` | Git proxy that pre-validates with review/test/docs/lint before pushing. | GitHub release (`kunchenguid/no-mistakes`) |
| `isolation-manager` | `treehouse` | Per-agent worktree pool. Opt-in. | GitHub release (`kunchenguid/treehouse`) |
| `overnight-runner` | `gnhf` | Long-running autonomous loops. Opt-in. | GitHub release (`kunchenguid/gnhf`) |
| `visual-collaboration` | `lavish-axi` | Local-first HTML authoring for plans, mockups, summaries. Opt-in. | `npm install -g lavish-axi` |
| `terminal-fallback` | `wezterm` | GPU-accelerated terminal. Opt-in. | `winget install wez.wezterm` / `brew install --cask wezterm` |

### 3.1 `firstmate` (orchestrator)

A per-project command orchestrator harness. Upstream ships a directory
of `bin/fm-*.sh` scripts + an `AGENTS.md` operating manual, **not a
single binary**. The workbench installs a shim that dispatches
`firstmate <verb>` to `fm-<verb>.sh`.

Common verbs (see `~/firstmate/AGENTS.md` for the full list):

| Verb | Purpose |
| --- | --- |
| `firstmate bootstrap` | First-time setup of a new project under firstmate. |
| `firstmate doctor` | Project-structure preflight. |
| `firstmate build` | Project build (the workbench's `agent-check` surfaces this). |
| `firstmate test` | Project test (the workbench's `agent-test` prefers this when `firstmate.toml` is present). |

The workbench calls into the shim, not into a binary, so the harness can be updated by `git pull` in `~/firstmate/` without re-running the installer.

### 3.2 `lavish-axi` (visual collaboration)

A local-first HTML authoring tool for human + AI collaboration on
plans, mockups, diagrams, comparison tables, and final summaries.
Used at steps 4 and 9 of the workflow (visual plan up front, visual
summary at the end). Opt-in — `agent-init --bootstrap=lavish-axi`.

### 3.3 `treehouse` (isolation-manager)

A pool of reusable git worktrees. `agent-fleet --backend treehouse`
leases N pre-warmed worktrees from the pool, which is faster than
asking `herdr` to create them from scratch. The worktrees return to
the pool when the agent exits. Opt-in — `agent-init --bootstrap=treehouse`.

### 3.4 `no-mistakes` (validation-gate)

A git proxy that pre-validates with review/test/docs/lint before
pushing. The workbench's `agent-check` calls `no-mistakes doctor` and
`no-mistakes status` and surfaces the output. Step 8 of the workflow.

### 3.5 `herdr` (agent-runtime)

A terminal multiplexer rebuilt for AI coding agents. Each pane is a
real PTY; herdr ships a built-in agent-state detector that watches the
prompt for Claude Code, Codex, OpenCode, Droid, Amp, Pi, Cursor Agent,
Kimi, Copilot CLI, Hermes, and more — surfacing a sidebar with 🔴
blocked / 🟡 working / 🔵 done / 🟢 idle.

CLI surface the workbench uses:

| Command | Why |
| --- | --- |
| `herdr status client` | probe whether the daemon is running |
| `herdr worktree create --cwd <repo> --label <name> --no-focus --json` | lease a worktree per agent |
| `herdr agent start <name> --cwd <wt> --split right --no-focus -- <claude>` | launch the agent in a new pane |
| `herdr agent wait <name> --status done --timeout <ms>` | block until the agent finishes |
| `herdr integration install claude` | one-time setup that registers the agent-state hook |

### 3.6 `claude` (model-runtime)

The Anthropic Claude Code CLI. The actual agent runtime. Reads the
system prompt from `<repo>/.agent/SYSTEM_PROMPT.md` (Claude Code's
default location) **and** from `--append-system-prompt <text>` (the
workbench passes the assembled prompt via this flag).

**Windows note:** The bare `claude` on PATH is a Node.js shim, not a
PE binary. `subprocess.run` calling `CreateProcessW` on it returns
`WinError 193: %1 is not a valid Win32 application`. The workbench
resolves `claude.cmd` (the actual Windows entry point) via
`utils.resolve_executable()` so this never happens.

### 3.7 `ollama` (model-runtime)

A local model runtime. Used as a fallback when `claude` is not
available. `agent-claude --backend=ollama` runs `ollama run <model>`.
The workbench never installs a specific model — `ollama pull <model>`
is the user's job.

### 3.8 `gnhf` (overnight-runner)

A loop driver that runs a coding agent (Claude Code, Codex, Copilot,
OpenCode, Pi, etc.) inside a git repo. Each successful iteration is a
separate commit. Aborts on `--max-iterations`, `--max-tokens`, or the
agent reporting `--stop-when`. Failed iterations get reset.

The workbench's `agent-overnight` wraps `gnhf` with safe defaults:
`--worktree` (isolated from the main checkout), `--max-iterations 50`,
`--max-tokens 100000`, and a preflight that refuses to run on a dirty
repo.

**gnhf on Windows:** As of 2026-07-06, gnhf ships no Windows release.
The default `agent-go` flow does not use gnhf; only `agent-overnight`
does. The default bootstrap does not pull gnhf on any platform.

### 3.9 `wezterm` (terminal-fallback)

A GPU-accelerated terminal. Optional alternative to herdr's own mux.
Opt-in — `agent-init --bootstrap=wezterm`.

---

## 4. Prompt generation: how the system prompt is built

The model sees one big system prompt. The workbench builds it from
six layers, each extending the previous. The order matters — layers
that come later override the policy of layers that come earlier
(specificity wins).

### 4.1 The merge order

| # | Layer | Source | Purpose |
| --- | --- | --- | --- |
| 1 | Global toolkit instructions | `AGENTS.md` (workbench root) | Engineering principles, code style, change discipline, output discipline, tool use, failure handling, boundaries, roles. **Always loaded first.** |
| 2 | Task-specific agent prompt | `prompts/<task>-agent.md` | Extends layer 1 with task-specific behaviour. Choices: `code`, `review`, `architecture`, `documentation`, `general`. |
| 3 | Detected technology profiles | `profiles/<stack>.md` | Stack-specific guidance. Loaded by `detect_stack` based on marker files. |
| 4 | Project-specific instructions | `AGENTS.project.md`, `CLAUDE.md`, `docs/agent-rules/*.md` | Your project's rules. **Overrides layers 1–3 for project-specific decisions.** |
| 5 | Generated repository summaries | `.agent/*.md` | Auto-generated by `agent-scan`. Loaded for context. |
| 6 | Extra instructions | Passed by the caller | Optional; used by `agent-fleet` for per-agent context, or for the `## Task` section appended from the positional argument. |

### 4.2 Why the order matters

- **Layer 1 first:** Every agent, on every project, must follow the same engineering principles. If a project rule contradicted a global rule, the global rule would be the one silently dropped, which is wrong direction.
- **Layer 2 second:** The task-specific role (code, review, architecture, documentation) shapes how the model behaves — but it does not override engineering principles. "Don't add comments" survives the review-agent overlay.
- **Layer 3 third:** Stack profiles add concrete advice ("use `EventCallback<T>` for events in Blazor"). They are advisory; project rules can still override.
- **Layer 4 fourth:** Project rules are the most specific — they win ties. If your `AGENTS.project.md` says "use snake_case for the database column names", that wins over the Blazor profile's "use PascalCase for parameters".
- **Layer 5 fifth:** The auto-generated summaries are context, not policy. They inform but do not override.
- **Layer 6 last:** The user-supplied task description is the most recent intent — it overrides everything below it for this turn only.

### 4.3 What goes in `AGENTS.project.md`

Drop this file in the repository root and the workbench picks it up
automatically. Suggested structure (from `examples/AGENTS.project.md`):

1. **Project overview** — one paragraph. What is this, who owns it, what stack.
2. **Domain rules** — business invariants the agent must respect. Off-limits tables, columns, APIs, configuration keys.
3. **Conventions specific to this repo** — naming patterns, file layout, internal libraries, intentional quirks.
4. **Non-goals** — what the agent must not do here. Be specific.
5. **Test data** — where the test database lives, how to seed it, how to reset it.
6. **Owners and contact** — who to ping for changes in each area.

### 4.4 What goes in `AGENTS.md` (the workbench's global rules)

You don't write this — it's the workbench's own file. It contains:

- **Engineering principles** — production-quality over draft-quality, maintainable over clever, smallest change that satisfies the request, etc.
- **Code style** — no comments unless documenting a non-obvious rule; match the surrounding code's idiom.
- **Change discipline** — touch only what the task requires; when refactoring, keep behaviour identical.
- **Output discipline** — reference code as `path:line`; quote exact error messages; distinguish "verified" from "inferred".
- **Tool use** — prefer dedicated file/search tools over shell equivalents; read a file before editing it.
- **Failure handling** — report failures with the actual output; say so when a step is skipped.
- **Boundaries** — do not push to remote, do not publish packages, do not modify global state without consent.
- **Roles and workflow** — the 8 roles and the 9-step workflow.

The full content is in `AGENTS.md` at the workbench root.

### 4.5 What the model sees

For a typical `agent-go --task code` invocation, the final system prompt is roughly:

```
<global-agent preamble>           ← from prompts/global-agent.md
<coding-agent preamble>           ← from prompts/coding-agent.md (--task code)
<blazor profile>                  ← from profiles/blazor.md (detected)
<your AGENTS.project.md>          ← from your repo
<.agent/repo-summary.md>          ← generated
<.agent/architecture.md>          ← generated
<.agent/build.md>                 ← generated
<.agent/commands.md>              ← generated
<.agent/dependencies.md>          ← generated
<.agent/coding-style.md>          ← generated
<optional task description>       ← from the positional argument
```

Total: typically 10–30 KB. The workbench prints the byte count and the list of files loaded when you run `agent-go`.

### 4.6 The "no quadratic blow-up" rule

The workbench never loads its own output back into a future prompt.
Files in `.agent/` named `SYSTEM_PROMPT.md`, `SYSTEM_PROMPT.fleet.md`,
or matching `SYSTEM_PROMPT.fleet-*.md` are filtered out by
`build_prompt.collect_agent_summaries()`. This is what keeps the
prompt size stable across `agent-go` invocations.

---

## 5. End-to-end workflows

This section walks through the workflows the workbench is designed
to support, with the exact command sequence for each.

### 5.1 New project from scratch (greenfield)

```powershell
# 1. Install the workbench on a fresh machine
iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1)

# 2. Open the (empty) repo
cd C:\code\new-project

# 3. Generate the .agent/ context
agent-scan

# 4. Sanity-check
agent-check

# 5. Create the project rules file
#    (write AGENTS.project.md — see section 4.3 for the structure)

# 6. Re-run agent-scan to pick up the new file
agent-scan

# 7. Launch the agent
agent-go --task code
```

### 5.2 Add a feature to an existing project

```powershell
cd C:\code\existing-project

# 1. Re-scan if the stack has changed
agent-scan

# 2. Sanity-check
agent-check

# 3. Launch with a specific task
agent-go --task code "Add a CSV export button to the tasks page"
```

### 5.3 Fix a bug

```powershell
cd C:\code\my-app

# 1. Re-scan if needed
agent-scan

# 2. Launch with the bug description
agent-go --task code "Fix the race condition in TaskBoardService.UpdateStatus where two concurrent updates lose the second write"
```

For non-trivial bugs, prefer the review prompt first:

```powershell
# Diagnose before changing
agent-go --task review "Investigate TaskBoardService.UpdateStatus for a race condition"

# Then fix based on the diagnosis
agent-go --task code "Apply the fix described in the diagnosis above"
```

### 5.4 Code review

```powershell
cd C:\code\my-app

# Review a branch or a set of changes
git checkout feature/new-export

agent-go --task review "Review the changes on this branch for correctness, security, and maintainability"
```

The review agent's priorities are: correctness, security, data
integrity, behaviour preservation, maintainability, style (only if
the project enforces it).

### 5.5 Refactoring

```powershell
cd C:\code\my-app

# State the interpretation up front
agent-go --task code "Refactor TaskBoardService to extract the validation logic into a separate TaskValidator class. Keep behaviour identical. Update the tests in TaskBoardServiceTests to cover the new class."
```

For refactors that touch many files, prefer `agent-fleet` to parallelise:

```powershell
agent-fleet 3 --task code --wait "Refactor the data access layer in src/Services/ to use the new IRepository<T> abstraction. Each agent handles one service."
```

### 5.6 Multi-agent parallel work

The `agent-fleet` command spawns N Claude agents in parallel, each in
an isolated context. Common patterns:

```powershell
# Three agents, each with the same task but their own worktree
agent-fleet 3 --task code "Add unit tests for all the services in src/Services/"

# Three agents with different per-agent context (via the prompt file)
# First, write .agent/SYSTEM_PROMPT.fleet-1.md, .agent/SYSTEM_PROMPT.fleet-2.md, .agent/SYSTEM_PROMPT.fleet-3.md
# Then run:
agent-fleet 3 --task code --wait

# Use treehouse-leased worktrees (faster, reusable)
agent-fleet 5 --task code --backend treehouse --wait
```

### 5.7 Overnight autonomous loop

```powershell
cd C:\code\my-app

# 1. Make sure the repo is clean
git status

# 2. Write the task to a file (version-controlled)
echo "Fix all CS8602 (possible null reference) warnings in src/" > overnight-task.md

# 3. Run the overnight loop
agent-overnight --task-file overnight-task.md

# By morning, the gnhf/<slug> branch has up to 50 commits, each addressing one warning.
```

For a CI/CD-like overnight job:

```powershell
# Push the gnhf branch after each successful iteration
agent-overnight --task-file overnight-task.md --push
```

### 5.8 Architecture exploration

For a new contributor trying to understand the codebase:

```powershell
cd C:\code\my-app

# 1. Generate context
agent-scan

# 2. Launch with the architecture task
agent-go --task architecture "Produce an architecture document for this repo. The output should follow the skeleton in the architecture-agent prompt: Purpose, Context, Modules, Key flows, Data, Cross-cutting concerns, Non-goals."
```

The architecture agent uses Mermaid for diagrams (plain text, renders
in GitHub). If a diagram needs more than 20 nodes, you do not yet
understand the system — ask questions first.

---

## 6. TeamTasksBoard walkthrough: from `dotnet new blazor` to working app

This is the worked example from the real-world testing that drove
the recent fixes. The repo is at
`C:\Users\henry\source\repos\TeamTasksBoard\TeamTasksBoard`. Follow
the steps to reproduce.

### 6.1 Create the project

```powershell
# 1. Create the Blazor Server project
cd C:\Users\henry\source\repos
dotnet new blazorserver -n TeamTasksBoard -o TeamTasksBoard
cd TeamTasksBoard

# 2. Initialise git (the workbench needs a repo to detect)
git init
git add -A
git commit -m "Initial commit: dotnet new blazorserver"
```

### 6.2 Install the workbench (if not already done)

```powershell
# One-line install
iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1)

# Verify
agent-go --print-cmd
```

### 6.3 Generate the workbench context

```powershell
# 1. Scan the repo
agent-scan

# Output:
#   .agent/repo-summary.md
#   .agent/architecture.md
#   .agent/build.md
#   .agent/commands.md
#   .agent/dependencies.md
#   .agent/coding-style.md

# 2. Sanity-check
agent-check
```

The `agent-check` output should show `[ok] profile: blazor (...)` and
`[ok] profile: dotnet (...)` based on the marker files
(`*.csproj` referencing `Microsoft.AspNetCore.Components.*` and the
`*.sln` solution file).

### 6.4 Write the project rules

Create `AGENTS.project.md` in the repo root:

```markdown
# AGENTS.project.md

TeamTasksBoard is a Blazor Server app for tracking team tasks. It uses
SQLite via Entity Framework Core.

## Domain rules

- Task status transitions: New → InProgress → Done. No skipping.
- Task deletion is soft (sets `DeletedAt`); never hard-delete a task.
- The `OwnerId` column is the current user's ID. Do not change the
  schema.

## Conventions

- Pages under `Pages/`, components under `Components/`, services under
  `Services/`.
- All services are registered as scoped in `Program.cs`.
- Use `bUnit` for component tests.

## Non-goals

- No multi-tenant support. The app assumes a single team.
- No mobile-specific layout. The desktop layout is the only layout.
- No external integrations (Slack, email, etc.) in this iteration.
```

### 6.5 Re-scan and re-check

```powershell
agent-scan    # picks up the new AGENTS.project.md
agent-check   # should now show "project instruction: AGENTS.project.md"
```

### 6.6 Launch the agent

```powershell
# Read-only: see the prompt
agent-go --task code --print-prompt | Out-File -Encoding utf8 .\my-prompt.md

# Full launch: opens a herdr pane with claude running
agent-go --task code
```

If herdr can't place the agent (e.g. a fresh repo with no commits),
the shim falls back to running `claude` in the current shell:

```powershell
agent-go --task code --no-herdr
```

### 6.7 First task: add the Task entity

In the herdr pane (or in the current shell with `--no-herdr`), paste:

```
Add the Task entity to the data model:

- Create src/TeamTasksBoard.Domain/Task.cs with properties: Id (Guid),
  Title (string, required, max 200), Description (string, optional),
  Status (enum: New, InProgress, Done), OwnerId (Guid),
  CreatedAt (DateTime), UpdatedAt (DateTime), DeletedAt (DateTime?, optional).
- Add the EF Core DbSet<Task> to ApplicationDbContext.
- Add a migration named "AddTaskEntity".
- Update Program.cs to register the DbContext.
```

The model will:

1. Read the surrounding files (the existing models, `Program.cs`, `appsettings.json`).
2. State its interpretation in 1–2 sentences.
3. Make the smallest change.
4. Call out any side effects (new migration, new service registration).
5. Run `dotnet build` and `dotnet test` if fast.

### 6.8 Verify

```powershell
# Run the test suite
agent-test

# Sanity-check
agent-check

# Review the changes
git diff
```

### 6.9 Iterate

For each new feature:

1. Re-run `agent-scan` if the project structure changed.
2. Run `agent-check` to surface any issues.
3. Launch with a specific task description.

For larger features that touch multiple services, use `agent-fleet`:

```powershell
agent-fleet 3 --task code --wait "Implement the tasks CRUD pages. Agent 1: Pages/Tasks.razor with the list view. Agent 2: Pages/TaskEdit.razor with the create/edit form. Agent 3: Services/TaskService.cs with the data access methods."
```

Each agent gets a fresh worktree, a separate herdr pane, and a copy of the prompt annotated with its index. They do not collide on disk.

> **Note:** `agent-fleet` does not auto-attach. With N agents, auto-attach would only work for one of them, so the shim instead prints the `herdr agent attach <name>` command for every agent and exits. Attach to any agent by name; the others keep running in their panes.

---

## 7. Windows-specific guide

This section covers the Windows-specific gotchas that have actually
hit during real-world testing. The full troubleshooting matrix is
in section 8.

### 7.1 The one-line install

```powershell
iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1)
```

What this does:

1. Clones the workbench into `~/.agent-workbench/`.
2. Drops PowerShell and bash shims into `~/.local/bin/`
   (`agent-go.ps1`, `agent-scan`, `agent-check`, etc.).
3. Asks before persisting `~/.local/bin` to your user PATH. The
   session-only `PATH` is always set so the rest of the install works
   either way.
4. Installs the bootstrap toolchain: `claude`, `herdr`, `firstmate`,
   `no-mistakes`, `ollama` (the slim default set; `treehouse`,
   `lavish-axi`, `gnhf`, `wezterm` are opt-in via `--bootstrap=<name>`).

Verify with:

```powershell
agent-go --print-cmd
```

That should print the one-liner above and exit 0.

### 7.2 The `claude.cmd` gotcha

`claude` on Windows PATH resolves to `C:\Users\henry\AppData\Roaming\npm\claude` — a
**bare Node.js shim**, not a PE binary. Python's `subprocess.run`
calls `CreateProcessW` on the path directly, which rejects non-PE
paths with:

```
OSError: [WinError 193] %1 is not a valid Win32 application
```

The fix is in `scripts/python/utils.py:resolve_executable()`. On
Windows, it tries `claude.cmd`, `claude.bat`, `claude.exe` in that
order, returning the first non-`None` hit. `.cmd` / `.bat` come
before `.exe` because the npm-published `claude` is a `.cmd` shim,
not an `.exe`. This fix is applied at every `subprocess.run` call
site (`agent-go`, `agent-claude`, `agent-fleet`, `bootstrap`).

If you are still seeing `WinError 193` after updating:

1. Confirm `claude.cmd` is on PATH:
   ```powershell
   Get-Command claude.cmd
   ```
   If that returns nothing, reinstall:
   ```powershell
   npm install -g @anthropic-ai/claude-code
   ```
2. Confirm the workbench is on the latest commit (the fix is in
   `scripts/python/utils.py`).

### 7.3 The herdr placement gotcha

The previous `agent-go` shim passed `--tab new` to
`herdr agent start`, but `--tab` expects an existing tab ID — `new`
is not a valid ID, so herdr returned:

```
agent placement target new not found
```

The fix is `--split right --no-focus`. The shim now:

1. Calls `herdr worktree create --cwd <repo> --label <name> --no-focus --json`
   (the `--cwd` is mandatory when no workspace is active). The JSON
   envelope is parsed to extract the actual worktree path.
2. If `worktree create` fails (e.g. `fatal: invalid reference: HEAD`
   on a fresh repo with no commits), the shim prints a clear info
   line and falls back to running the agent in the repo root.
3. Calls `herdr agent start <name> --cwd <worktree> --split right --no-focus -- <claude>`.
   The `--cwd` value is the path extracted from step 1, not the
   raw JSON envelope.
4. Parses the `agent_started` JSON envelope to verify the agent's
   actual cwd matches the worktree path. If herdr landed the agent
   somewhere else (a herdr bug, a stale workspace), prints a
   `[warn]` line so the user knows to look at the pane.
5. If `agent start` fails for any other reason (server wedged, agent
   name taken, etc.), the shim prints a clear info line and falls
   back to direct `claude` invocation.

**Auto-attach:** Once the agent is up, the shim prints an instruction
block and (if stdout is a TTY and `AGENT_GO_NO_AUTO_ATTACH` is not
set) attempts `herdr agent attach <name>` so the user's terminal
lands directly in the agent's pane. If `herdr agent attach` returns
non-zero, the agent is still running; the user can attach manually
with the same command. Pass `--no-attach` to skip this step in CI.

### 7.4 The `gnhf` gotcha

`gnhf` is the overnight runner. As of 2026-07-06, it has no Windows
release. The previous `agent-go` included `gnhf` in
`DEFAULT_GO_BOOTSTRAP`, which meant every Windows `agent-go` hit
the honest-but-noisy "no asset matching" error from the bootstrap
step.

The fix: `gnhf` is no longer in the default bootstrap. The slim
default is now `claude,herdr,firstmate,no-mistakes,ollama`. To use
overnight on Windows, install `gnhf` manually from source.

### 7.5 The `--print-prompt` gotcha

The previous `agent-go --print-prompt` ran the full bootstrap step
first (which tried to install `gnhf`, which produced a noisy error)
even though the user just wanted to read the prompt. The fix:
`--print-prompt` is now a true no-op read path — no install, no
herdr, no model launch.

### 7.6 The PowerShell `ExecutionPolicy` gotcha

If PowerShell blocks the installer:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 7.7 The symlink permission gotcha

If `agent-init.ps1` cannot create symlinks (no privileges), it falls
back to copying the scripts into `%USERPROFILE%\.local\bin\`. Add
that directory to your PATH if it is not already:

```powershell
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
```

### 7.8 The `PATH` for the current session

Even if you do not persist the PATH change, the workbench adds
`~/.local/bin` to the PATH for the current process, so the rest of
the install works. To persist:

```powershell
[Environment]::SetEnvironmentVariable("Path", "$env:USERPROFILE\.local\bin;$env:Path", "User")
```

### 7.9 The full Windows quickstart

```powershell
# 1. One-time install
iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1)

# 2. Open the repo
cd C:\path\to\your\repo

# 3. Generate the .agent/ context
agent-scan

# 4. Sanity-check
agent-check

# 5. Launch the agent
agent-go --task code
```

If the herdr pane does not open, the fallback is:

```powershell
agent-go --task code --no-herdr
```

If even that fails, the read-only path is:

```powershell
agent-go --task code --print-prompt | Out-File -Encoding utf8 .\my-prompt.md
```

---

## 8. Troubleshooting

This section covers every issue encountered during real-world testing,
with the exact error message, the cause, and the fix.

### 8.1 `WinError 193: %1 is not a valid Win32 application`

**Cause:** `subprocess.run` called `CreateProcessW` on a bare Node.js shim path (`claude` without `.cmd` extension on Windows).

**Fix:** `utils.resolve_executable()` tries `claude.cmd` / `claude.bat` / `claude.exe` before falling back to the bare name. Ensure you are on the latest commit. Confirm `claude.cmd` is on PATH:

```powershell
Get-Command claude.cmd
```

If absent, reinstall:

```powershell
npm install -g @anthropic-ai/claude-code
```

### 8.2 `agent placement target new not found`

**Cause:** `herdr agent start` was called with `--tab new`, but `--tab` expects an existing tab ID.

**Fix:** Use `--split right --no-focus` instead. This is now the default in the workbench's `agent_go.py` and `agent_claude.py`. Update your checkout.

### 8.3 `workspace_id or cwd is required when no workspace is active`

**Cause:** `herdr worktree create` was called without `--cwd` and no herdr workspace was active.

**Fix:** Pass `--cwd <repo>` to `herdr worktree create`. This is now the default in the workbench's `agent_go.py` and `agent_claude.py`. Update your checkout.

### 8.4 `fatal: invalid reference: HEAD`

**Cause:** `herdr worktree create` failed because the repo has no commits yet. Not fatal — the shim catches this and falls back to the repo root.

**Fix:** None required; the shim handles it. If you want a clean worktree, commit your changes first:

```powershell
git add -A
git commit -m "wip"
```

Then re-run `agent-go`.

### 8.5 `--print-prompt` triggered a noisy bootstrap with `no asset matching gnhf`

**Cause:** The previous `--print-prompt` ran the full bootstrap step first, which tried to install `gnhf` (overnight runner with no Windows release).

**Fix:** `--print-prompt` is now a true no-op read path — no install, no herdr, no model launch. `gnhf` is no longer in `DEFAULT_GO_BOOTSTRAP`. Update your checkout.

### 8.6 `dispatch.py: error: argument --repo: expected one argument`

**Cause:** A previous version of the `agent-go.ps1` shim pre-declared `--repo` in its `param()` block, which injected an empty `--repo ""` before the user's args reached the parser.

**Fix:** The shim now uses `[Parameter(ValueFromRemainingArguments = $true)]` and forwards all args verbatim. The same fix was applied to all 10 shims.

### 8.7 `firstmate: legacy no-ext shim at ...`

**Cause:** A previous (buggy) install dropped a bare `firstmate` shim (no `.cmd` extension) on Windows. The bare shim was dead — it exec'd a non-existent `bin/firstmate` file. The Windows PATH lookup prefers `firstmate.cmd`, so the legacy shim is harmless but takes up disk space.

**Fix:** None required. The current install drops a `firstmate.cmd` shim that correctly dispatches to the harness. You can manually delete the legacy `firstmate` file if you want to clean up.

### 8.8 `no-mistakes: not initialized`

**Cause:** `no-mistakes` is installed but `no-mistakes init` has not been run for the repo.

**Fix:**

```bash
cd /path/to/repo
no-mistakes init
```

`agent-check` will surface this and the `no-mistakes status` call will be skipped until the gate is initialized.

### 8.9 `claude: command not found` on Windows

**Cause:** The `claude` CLI is not on PATH. This usually means the npm install was not completed or the PATH was not refreshed.

**Fix:**

```powershell
# Reinstall
npm install -g @anthropic-ai/claude-code

# Refresh PATH for the current session
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
# Or, for PowerShell, %APPDATA%\npm is also on PATH if npm's installer added it
```

### 8.10 `python: command not found` from a Git Bash shim

**Cause:** The Windows App Execution Alias can hijack a bare `python` call from a non-MSYS shell. The bash shim on Windows prefers the PowerShell wrapper to avoid this.

**Fix:** Use the PowerShell shim (`agent-go.ps1`) instead of the bash shim. The bash shim is only there for Git Bash / WSL users who do not have PowerShell readily available.

### 8.11 `herdr server did not respond within 5s`

**Cause:** The herdr server failed to start within the 5-second poll window. This can happen on a slow machine or if another herdr process is already bound to the socket.

**Fix:** The shim continues anyway and falls back to direct `claude` if needed. To debug:

```powershell
# Check if herdr is running
Get-Process herdr -ErrorAction SilentlyContinue

# Check the socket
Test-Path $env:USERPROFILE\.herdr\herdr.sock
```

If herdr is wedged, kill it and let the workbench restart it:

```powershell
Get-Process herdr | Stop-Process -Force
agent-go --task code
```

### 8.12 `agent-check` reports `firstmate: not installed`

**Cause:** The `firstmate` harness is not at `~/firstmate/AGENTS.md` and the shim is not on PATH.

**Fix:**

```bash
agent-init --bootstrap=firstmate
```

This clones `github.com/kunchenguid/firstmate` to `~/firstmate/` and drops the `firstmate.cmd` shim into `~/.local/bin/`.

### 8.13 `agent-check` reports `no-mistakes: not installed`

**Cause:** The `no-mistakes` binary is not at `~/.local/bin/no-mistakes[.exe]`.

**Fix:**

```bash
agent-init --bootstrap=no-mistakes
```

### 8.14 `agent-fleet` reports `worktree create failed for fleet-N`

**Cause:** The `herdr worktree create` call failed for one of the agents. This is non-fatal — the shim falls back to the repo root for that agent.

**Fix:** Check the stderr in the info line. Common causes:

- `fatal: invalid reference: HEAD` — commit your changes first.
- `workspace_id or cwd is required` — internal herdr bug; try `herdr status client` to verify the server is healthy.
- The repo is locked by another process.

### 8.15 `agent-fleet` reports `herdr agent start failed for fleet-N`

**Cause:** The `herdr agent start` call failed for one of the agents. The shim records the failure and continues with the next agent.

**Fix:** Check the stderr in the info line. Common causes:

- `agent placement target new not found` — outdated checkout; pull the latest.
- `agent name taken` — wait for the previous fleet to finish, or use different names.
- The herdr server is wedged — restart it.

### 8.16 `agent-overnight` refuses to run on a dirty repo

**Cause:** The preflight check refuses to run `gnhf` on a dirty repo to prevent your WIP from being mixed into the gnhf commit log.

**Fix:** Either commit/stash your changes first, or pass `--allow-dirty` to override (not recommended).

### 8.17 `agent-overnight` reports `gnhf is not installed`

**Cause:** `gnhf` is opt-in via `agent-init --bootstrap=gnhf` and is not in the default install.

**Fix:**

```bash
agent-init --bootstrap=gnhf
```

Note: `gnhf` ships no Windows release as of 2026-07-06. On Windows you would need to build from source.

### 8.18 The agent ignores `AGENTS.project.md`

**Cause:** `agent-scan` was not re-run after the project rules were added. The `.agent/` directory was generated before the file existed, but the workbench loads `AGENTS.project.md` from the repo root directly, not from `.agent/`. Check that the file is actually in the repo root:

```bash
ls AGENTS.project.md
```

If the file is in a subdirectory, the workbench will not find it. Move it to the repo root.

### 8.19 The system prompt is too large (> 50 KB)

**Cause:** The repo has many large files, the `AGENTS.project.md` is verbose, or the stack profiles are pulling in extra context.

**Fix:**

- Trim `AGENTS.project.md` to the essentials. Move detailed reference material to a separate file under `docs/` (the workbench does not load arbitrary `docs/` files into the prompt, only `docs/agent-rules/*.md`).
- Check `.agent/repo-summary.md` — if the language breakdown is dominated by a single language (e.g. 1M lines of generated code), the workbench is scanning generated files. Add the generated directory to `scan_repo.EXCLUDE_DIRS`.
- The default `claude` model has a 100K context window. 30 KB is fine; 50 KB is the warning zone; 100 KB will not fit.

### 8.20 The agent's diff is too large

**Cause:** The agent decided to rewrite a whole file instead of editing the minimum.

**Fix:**

- Re-prompt with a more specific scope: "Edit only the `UpdateStatus` method in `TaskBoardService.cs`. Do not change other methods."
- Use the "what not to do" guidance from the coding-agent prompt: "Do not reformat unrelated lines. Touch only what the task requires."
- If the agent is consistently producing overly large diffs, add a project rule: "Always produce the smallest diff that satisfies the request. If a refactor would touch > 5 files, ask for confirmation first."

### 8.21 The agent lands in `C:\Users\henry\` instead of the worktree

**Cause:** A previous version of the workbench passed the entire `worktree_created` JSON envelope as `--cwd` to `herdr agent start`. herdr silently fell back to the user's home directory on the invalid path.

**Fix:** The shim now parses the `worktree_created` envelope and passes the actual `worktree.path` string. If you still see a `[warn]` line from `agent-go` like `herdr agent started in <home>, expected <worktree>; the agent may be in the wrong directory`, file a bug with the full output — that means herdr accepted the spawn but landed the agent somewhere unexpected.

### 8.22 `agent-go` returned me to the PowerShell prompt with no clear next step

**Cause:** A previous version of `agent-go` printed only "herdr agent 'primary' started" and exited, leaving the user at a normal prompt with no obvious way to interact with the agent.

**Fix:** The shim now prints a 7-line instruction block (repo, worktree, agent cwd, agent name, attach command) and, if stdout is a TTY, auto-attaches the terminal to the agent's pane via `herdr agent attach primary`. To opt out of the auto-attach and keep the old "print and exit" behavior, use `--no-attach` or set `AGENT_GO_NO_AUTO_ATTACH=1` in the environment.

### 8.23 `agent-go` says `Claude Code opened but is not logged in`

**Cause:** You have the `claude` runtime selected (the default) and Claude Code is not authenticated. The login probe (env vars + credentials file + legacy `~/.claude.json`) did not find any credentials.

**Fix:** Pick a different runtime. The message includes the exact two commands to use:

```
agent-go --task code --runtime ollama --model <model>
agent-go --task code --runtime openai-compatible --model <model> --base-url <url>
```

Or set up Claude Code login (one of):

- `claude /login` inside the Claude Code TUI (OAuth flow).
- `export ANTHROPIC_API_KEY=sk-…` in your shell (or via your secret manager).
- Drop a `~/.claude/.credentials.json` with a valid token.

### 8.24 `agent-go` says `no model runner found`

**Cause:** The default `claude` runtime could not find the `claude` CLI on PATH (or it is installed but the binary is not a real Windows executable), and the ollama fallback was also missing. This is the unhappy case where neither Anthropic nor Ollama is installed.

**Fix:** Pick a runtime that you actually have installed:

```bash
# Install ollama (Windows)
winget install Ollama.Ollama

# Or install claude (cross-platform)
npm install -g @anthropic-ai/claude-code
```

Or point at an OpenAI-compatible provider that you have running:

```bash
agent-go --task code --runtime openai-compatible \
         --base-url http://localhost:1234/v1 \
         --api-key-env OPENAI_API_KEY
```

---

## 9. Best practices

### 9.1 For small projects (≤ 5 services, single dev)

- The slim default bootstrap is enough. You do not need `treehouse`, `lavish-axi`, `gnhf`, or `wezterm`.
- `agent-scan` is fast (< 5 s) and should run on every major change to the project structure.
- `agent-go --task code` is the only command you need for the hot path. `--no-herdr` if you do not have a graphical terminal.
- Skip `agent-fleet` — there is no parallel work to coordinate.

### 9.2 For large projects (multiple services, multiple devs)

- Run `agent-check` in CI. The exit code is 0 on pass, 1 on fail. The output is one finding per line, easy to grep.
- Use `agent-fleet` for large refactors that touch multiple services. The herdr backend is the default; treehouse is faster for repeated fleets.
- Add `no-mistakes init` to the repo so every push goes through the validation gate.
- Add a project rule in `AGENTS.project.md` for anything that is not obvious from the code (ownership, non-goals, test data).

### 9.3 For greenfield projects

- Run `agent-scan` early. The auto-generated summaries help the agent understand the structure before it has read the code.
- Write `AGENTS.project.md` before the first `agent-go` invocation. Without it, the agent will guess at conventions.
- Prefer the `architecture` task first to get a high-level overview, then `code` for implementation.

### 9.4 For existing projects (brownfield)

- Run `agent-scan` and `agent-check` first to see what the workbench detects. Pay attention to:
  - The detected stack — if the Blazor profile is loaded but the project is actually WPF + WinForms, the agent will produce wrong advice.
  - The `.agent/` summaries — if `repo-summary.md` is dominated by generated code, exclude that directory in `scan_repo.EXCLUDE_DIRS`.
- Add an `AGENTS.project.md` that names the things the agent would otherwise guess wrong: the test data location, the "do not touch" tables, the owners.
- Use `agent-go --task review` first to surface issues before making changes.

### 9.5 For solo work

- The workbench is a single-user tool. There is no shared state. Each `agent-go` invocation is independent.
- Do not run `agent-fleet` with more than 3 agents on a single machine unless you have a powerful CPU. Each agent is a full `claude` process.
- Do not run `agent-overnight` without `--allow-dirty` having been considered. The preflight is there for a reason.

### 9.6 For team work

- Commit `AGENTS.project.md` to the repo. Every team member's `agent-go` will pick it up.
- Commit `.agent/` to the repo. It is auto-generated, but committing it means every team member sees the same context, and CI can diff it to detect when the stack changes unexpectedly.
- Add a `make agent-check` (or equivalent) target to the project's build. Make CI run `agent-check` and fail on `[err]`.
- Use `no-mistakes` as the git proxy. `no-mistakes install` once per dev machine; the pre-push hook is then automatic.

### 9.7 For CI/CD

- The workbench is not a CI system. Do not try to make `agent-go` run in CI — it is interactive.
- Use `agent-check` in CI. The output is one finding per line; grep for `[err]` to detect failures.
- For overnight runs that should be triggered by CI, use `agent-overnight --task-file <path> --push` in a cron job or a scheduled workflow.

### 9.8 For PR reviews

- Use `agent-go --task review "Review the changes on this branch"`. The review agent's priorities are: correctness, security, data integrity, behaviour preservation, maintainability, style.
- For multi-PR reviews, use `agent-fleet 3 --task review --wait "Review the three open PRs"`.
- Do not block on style when the project does not enforce style. The review agent is configured to know this.

### 9.9 Security

- The workbench never reads files outside the repository. It does not exfiltrate code or send it to a remote service other than the configured model runner.
- The system prompt is the only thing the model sees about your repo. It is assembled locally and written to `.agent/SYSTEM_PROMPT.md`. Check this file if you are worried about what is being sent.
- The workbench never modifies global system state, dotfiles, or PATH outside the installer's documented scope.
- If you find a security issue, the `.agent/` summaries do not include secrets by design (the `EXCLUDE_FILE_SUFFIXES` set in `scan_repo.py` excludes `.env`, `credentials.json`, `service-account.json`).

### 9.10 Performance

- `agent-scan` is O(n) in the number of files in the repo. For repos with > 100K files, exclude `node_modules`, `bin`, `obj`, etc. (already in the default `EXCLUDE_DIRS`).
- `agent-go` is dominated by the model's inference time, not the prompt assembly. The assembly step is < 100 ms.
- `agent-fleet` is parallel; the wall-clock time is the slowest single agent, not the sum.
- `agent-overnight` is bounded by `--max-iterations` (default 50) and `--max-tokens` (default 100K). On a typical project, an overnight run will saturate one of those limits.

---

## 10. Developer reference

### 10.1 Cheat sheet

```bash
# One-time install
agent-init

# Per-session flow
cd /path/to/repo
agent-scan                       # generate .agent/ context
agent-check                      # validate
agent-go --task code             # launch the agent

# Common variants
agent-go --task code --print-prompt | less    # see the prompt
agent-go --task code --no-herdr                # skip herdr, run inline
agent-go --task code --no-attach               # start detached, print attach command
agent-go --task code --no-bootstrap            # assume tools are installed
agent-fleet 3 --task code --wait               # spawn 3 parallel agents
agent-overnight --task-file task.md            # overnight loop
agent-test                                       # run the test suite
agent-bootstrap --check --json                  # check tool health
```

### 10.2 Decision tree

```
Want to ...
├── install on a fresh machine?
│   └── agent-init
├── add a tool?
│   └── agent-init --bootstrap=<name>
├── open a repo for the first time?
│   ├── agent-scan
│   └── agent-check
├── write code?
│   └── agent-go --task code
├── review a PR?
│   └── agent-go --task review
├── design or document architecture?
│   └── agent-go --task architecture
├── write or update docs?
│   └── agent-go --task documentation
├── run multiple agents in parallel?
│   ├── agent-fleet N --task code
│   └── (use --wait to block)
├── run an overnight loop?
│   └── agent-overnight --task-file task.md
├── run the test suite?
│   └── agent-test
├── see the system prompt?
│   ├── agent-go --task code --print-prompt
│   └── agent-review --output prompt.md
└── validate the repo?
    └── agent-check
```

### 10.3 Directory structure of the workbench itself

```
agent-workbench/
├── AGENTS.md                          # global rules, loaded first into every prompt
├── README.md                          # repo overview
├── AGENT_WORKBENCH_USER_GUIDE.md      # this file
├── WINDOWS_USAGE.md                   # Windows-specific quickstart
├── CHANGELOG.md                       # release notes
├── LICENSE                            # MIT
├── prompts/                           # task-specific agent prompts
│   ├── global-agent.md
│   ├── coding-agent.md
│   ├── review-agent.md
│   ├── architecture-agent.md
│   └── documentation-agent.md
├── profiles/                          # technology profiles
│   ├── blazor.md
│   ├── dotnet.md
│   ├── react.md
│   ├── angular.md
│   ├── node.md
│   ├── python.md
│   ├── java.md
│   ├── docker.md
│   ├── mysql.md
│   └── wso2-mi.md
├── tools/                             # per-tool documentation
│   ├── roles.md
│   ├── firstmate.md
│   ├── lavish-axi.md
│   ├── treehouse.md
│   ├── no-mistakes.md
│   ├── herdr.md
│   ├── gnhf.md
│   ├── wezterm.md
│   ├── tmux.md
│   └── kunchenguid.md
├── scripts/
│   ├── python/                        # source of truth — all business logic
│   │   ├── dispatch.py                # thin dispatcher
│   │   ├── utils.py                   # shared utilities + resolve_executable
│   │   ├── build_prompt.py            # prompt assembly
│   │   ├── scan_repo.py               # .agent/ generation
│   │   ├── detect_stack.py            # profile matching
│   │   ├── bootstrap.py               # dependency installation
│   │   ├── install.py                 # agent-init
│   │   ├── agent_init.py              # (alternate entry)
│   │   ├── agent_go.py                # agent-go
│   │   ├── agent_claude.py            # agent-claude
│   │   ├── agent_check.py             # agent-check
│   │   ├── agent_test.py              # agent-test
│   │   ├── agent_fleet.py             # agent-fleet
│   │   ├── agent_overnight.py         # agent-overnight
│   │   └── agent_doctor.py            # firstmate/no-mistakes health checks
│   ├── bash/                          # bash shims (unix + Windows Git Bash)
│   │   ├── agent.sh                   # dispatcher
│   │   ├── agent-init
│   │   ├── agent-scan
│   │   ├── agent-check
│   │   ├── agent-review
│   │   ├── agent-test
│   │   ├── agent-claude
│   │   ├── agent-bootstrap
│   │   ├── agent-fleet
│   │   ├── agent-go
│   │   └── agent-overnight
│   └── powershell/                    # PowerShell shims (Windows)
│       ├── agent-go.ps1
│       ├── agent-init.ps1
│       ├── agent-scan.ps1
│       ├── agent-check.ps1
│       ├── agent-review.ps1
│       ├── agent-test.ps1
│       ├── agent-claude.ps1
│       ├── agent-bootstrap.ps1
│       ├── agent-fleet.ps1
│       └── agent-overnight.ps1
├── tests/                             # pytest suite
│   └── test_windows_command_resolution.py  # 16 tests for the .cmd fix
└── examples/                          # sample AGENTS.project.md
    ├── AGENTS.project.md
    ├── blazor/
    ├── dotnet-api/
    └── wso2-mi/
```

### 10.4 Environment variables

| Variable | Effect | Default |
| --- | --- | --- |
| `AGENT_MODEL` | Override the model name. | `minimax-m3:cloud` |
| `AGENT_GO_NO_AUTO_ATTACH` | Disable the auto-attach attempt after `agent-go --task code`. Set to `1` / `true` / `yes` / `on`. | unset (auto-attach on) |
| `AGENT_WORKBENCH_HOME` | Override the workbench root. | `~/.agent-workbench/` |
| `AGENT_WORKBENCH_BIN` | Override the helper shim directory. | `~/.local/bin/` |
| `AGENT_WORKBENCH_REPO` | Override the auto-detected repo root. | (none) |
| `PYTHONPATH` | Standard Python path. The shims set this to include `scripts/python/`. | (system) |

### 10.5 Resolution order for the model

1. `--model <name>` on the command line.
2. `$AGENT_MODEL` environment variable.
3. `model = "..."` line in `~/.agent-workbench/config.toml`.
4. Built-in default: `minimax-m3:cloud`.

### 10.6 Resolution order for the repo root

1. `--repo <path>` on the command line.
2. `$AGENT_WORKBENCH_REPO` environment variable.
3. Walk upward from the current directory looking for: `.git`, `AGENTS.project.md`, `CLAUDE.md`, or any of the technology-specific manifest files (`package.json`, `pyproject.toml`, `*.csproj`, `pom.xml`, etc.).
4. Fall back to the current directory.

### 10.7 Where the prompts and profiles live

The workbench ships its own `prompts/`, `profiles/`, and `AGENTS.md` at the workbench root. To override any of these for a project, drop a file with the same name in your repo root (for `AGENTS.project.md`) or under `docs/agent-rules/` (for additional rules). The project's file wins.

### 10.8 Where the workbench installs to

| Path | Contents |
| --- | --- |
| `~/.agent-workbench/` | The workbench root (if you ran `agent-init` from a clone) or the install root (if you ran the one-line installer). |
| `~/.local/bin/` | The 10 helper shims (`agent-go`, `agent-scan`, etc.) and the workbench marker file `agent-workbench-home`. |
| `<repo>/.agent/` | The auto-generated summaries and the last-written `SYSTEM_PROMPT.md`. |
| `~/firstmate/` | The `firstmate` harness (cloned by the bootstrap step). |
| `~/.claude/hooks/herdr-agent-state.ps1` | The herdr integration hook (written by `herdr integration install claude`). |
| `~/.herdr/herdr.sock` | The herdr server socket. |

### 10.9 Adding a new technology profile

1. Create `profiles/<name>.md` in the workbench root.
2. Add a `Detector` entry in `scripts/python/detect_stack.py:DETECTORS`:
   ```python
   Detector("<name>", "<name>.md", [], [<predicate>])
   ```
3. Add a predicate function that returns a list of evidence strings (or empty list if the repo does not match):
   ```python
   def _has_<name>(repo: Path) -> list[str]:
       evidence: list[str] = []
       if (repo / "<marker>").is_file():
           evidence.append("<marker> present")
       return evidence
   ```
4. Add a test in `tests/test_detect_stack.py` (or extend the existing one).

The profile is auto-loaded into every prompt for repos that match.

### 10.10 Adding a new command

1. Create `scripts/python/agent_<name>.py` with a `main(argv: list[str] | None = None) -> int` function.
2. Add the command to `scripts/python/dispatch.py:COMMANDS`:
   ```python
   COMMANDS = {
       ...
       "<name>": "agent_<name>",
   }
   ```
3. Add a shim in `scripts/bash/agent-<name>` and `scripts/powershell/agent-<name>.ps1`. The shims are thin pass-throughs; all argument parsing happens in the Python module.
4. Add the shim to `scripts/python/install.py:HELPERS` so `agent-init` installs it.
5. Add tests in `tests/test_<name>.py`.

### 10.11 Where to get help

- This document (you are reading it).
- The workbench's own `AGENTS.md` (the rules every agent follows).
- The `tools/` directory in the workbench root (per-tool documentation).
- The `prompts/` directory (the task-specific agent prompts).
- The `profiles/` directory (the technology profiles).
- `agent-check` (the lightweight validator).
- `agent-go --print-prompt` (the read-only path to see the system prompt).
- GitHub issues at `github.com/maestroohk/agent-workbench`.

---

*This document is maintained alongside the workbench. If you find
something that is wrong or out of date, please open an issue or a
PR at `github.com/maestroohk/agent-workbench`.*
