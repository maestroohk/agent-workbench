# agent-workbench

A cross-platform AI development toolkit. One source of truth for global instructions, project rules, repository summaries, and the launch command for your preferred local model. Works on Windows 10/11, Linux, WSL, and Docker development containers.

## Goals

- Reusable global AI instructions that travel with the toolkit.
- Per-repository project instructions that are auto-discovered.
- Automatic repository scanning, stack detection, and prompt assembly.
- A single launcher that puts the right context in front of the model.
- Helper commands for the common workflows: init, scan, check, review, test.

## Mental model

The workbench orchestrates external tools, each filling a specific
**role** at a specific point in the workflow. The roles are stable;
the tools that fill them can change. `axi` is a design philosophy for
agent-native CLIs (concise, structured, low-token); it is not a tool.

After a clean install, this is the loop a session follows:

1. Bootstrap / install prerequisites.
2. Verify PATH / tool availability — without silently editing shell profiles.
3. Scan the target repo and generate concise `.agent/` context.
4. Create a visual plan with lavish-axi when the task is complex or UI-related.
5. Use firstmate to delegate work to specialized agents.
6. Use treehouse for isolated worktrees for agent tasks.
7. Run project tests / checks.
8. Run no-mistakes as the final validation gate.
9. Produce a concise final report — preferably with lavish-axi if visual review is useful.

The full role taxonomy is in `tools/roles.md`. The short version:

| Role | Tool | What it is |
| --- | --- | --- |
| `orchestrator` | firstmate | Multi-agent harness. Top-level coordination. |
| `visual-collaboration` | lavish-axi | Plans, mockups, diagrams, summaries. |
| `isolation-manager` | treehouse | Per-agent worktree pool. |
| `validation-gate` | no-mistakes | Pre-push review/test/lint gate. |
| `overnight-runner` | gnhf | Long-running autonomous loop. |
| `agent-runtime` | herdr | Multiplexer for panes + worktrees. |
| `model-runtime` | claude / ollama | The actual model runner. |
| `terminal-fallback` | wezterm | Optional GPU terminal. |

## Architecture

```
agent-workbench/
├── AGENTS.md            # global instructions (always loaded)
├── README.md
├── LICENSE
├── CHANGELOG.md
├── prompts/             # global agent system prompts
├── profiles/            # stack-specific guidance (dotnet, react, ...)
├── tools/               # companion-tool documentation (tmux, wezterm, ...)
├── scripts/
│   ├── python/          # SOURCE OF TRUTH — all business logic
│   ├── bash/            # thin wrappers that invoke python
│   └── powershell/      # thin wrappers that invoke python
├── examples/            # sample AGENTS.project.md and stack examples
└── .agent/              # generated per-repo summaries (created on scan)
```

Python is the single source of truth. Bash and PowerShell only dispatch.

## Installation

### One-line install (Linux / WSL / macOS / Git Bash)

```bash
git clone https://github.com/<your-org>/agent-workbench.git
cd agent-workbench
./scripts/bash/agent-init.sh
```

`agent-init` will:

- detect the platform
- create `~/.agent-workbench/` as the install root
- symlink (or copy on Windows without privileges) the helper scripts into `~/.local/bin/` or `%USERPROFILE%\.local\bin\`
- print a short report of what changed

### One-line install (Windows PowerShell)

```powershell
iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1)
```

This single line clones the toolkit into `~/.agent-workbench/`, symlinks
the helper shims into `~/.local/bin/`, adds that directory to your user
PATH (no admin required), and bootstraps the slim default set:
`claude`, `herdr`, `firstmate`, `no-mistakes`, `ollama`. gnhf and
treehouse are opt-in (the installer does not pull them on a clean
install; `agent-init --bootstrap=gnhf,treehouse` adds them later).

### Docker

```dockerfile
COPY agent-workbench /opt/agent-workbench
RUN /opt/agent-workbench/scripts/bash/agent-init.sh
ENV PATH="/root/.local/bin:${PATH}"
```

## Usage

After installation, the following commands are available on `PATH`:

| Command         | Purpose                                                   |
| --------------- | --------------------------------------------------------- |
| `agent-init`    | Install or update the toolkit and its external dependencies |
| `agent-go`      | One-liner cold-machine bootstrap: install missing tools, start herdr, run claude with the global rules pre-applied |
| `agent-bootstrap` | Install external dependencies (herdr, firstmate, no-mistakes) on demand |
| `agent-scan`    | Generate `.agent/` summaries for the current repository   |
| `agent-check`   | Validate the repository (structure, firstmate harness, no-mistakes doctor) |
| `agent-review`  | Print a review-ready system prompt for the repo           |
| `agent-test`    | Run the detected test suite (firstmate has no `test` subcommand upstream; this is the workbench's own test runner) |
| `agent-claude`  | Launch Claude Code (or ollama) with the assembled system prompt |
| `agent-fleet`   | Spawn N Claude agents in parallel, each in an isolated herdr pane and worktree |
| `agent-overnight` | Run a `gnhf` overnight loop with safe defaults (worktree, iteration + token caps, dirty-repo preflight) |

### Cold-machine flow (one line)

```powershell
iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1)
```

That single line takes a fresh Windows box to a fully-set-up toolkit.
On a fresh macOS / Linux / WSL box:

```bash
curl -fsSL https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.sh | sh
```

After that, on any repo:

```bash
cd ~/code/my-project
agent-go                       # installs any missing tool, starts herdr in the background,
                               # then launches `claude` in a herdr pane with the
                               # global rules (AGENTS.md + repo summaries + project
                               # instructions) auto-applied.
```

Flags:

- `agent-go --task code` — layer in the coding-agent prompt
- `agent-go --task review` — layer in the review-agent prompt
- `agent-go --no-bootstrap` — skip the install step (tools already present)
- `agent-go --no-herdr` — run `claude` in the current shell, no herdr isolation
- `agent-go --print-cmd` — print the one-liner and exit (handy for docs)
- `agent-go --print-prompt` — print the assembled prompt to stdout and exit
  (read-only: no install, no herdr, no model launch)

The other tools (`no-mistakes`, `gnhf`, `lavish-axi`, `agent-fleet`)
are on PATH and used by Claude Code as needed. See `tools/roles.md`
for the full role taxonomy and the 9-step workflow each session follows.

### Windows-specific notes

`agent-go` on a fresh Windows box has had three silent-failure modes
that this round removes:

1. `subprocess.run([claude])` blew up with
   `OSError: [WinError 193] %1 is not a valid Win32 application`
   because the bare `claude` on PATH is a Node.js shim, not a PE
   binary. Now resolved via `utils.resolve_executable()` to the
   real `claude.cmd` (or `.bat` / `.exe`).
2. `herdr agent start` rejected `--tab new` (`agent placement
   target new not found`) and the shim silently returned 0. Now
   uses `--split right --no-focus` and routes failures to a
   direct-claude fallback.
3. `--print-prompt` triggered a noisy bootstrap that hit
   `gnhf has no Windows release` even though the user just wanted
   to read the prompt. Now `--print-prompt` is a true read-only
   no-op.

For the full screen-by-screen Windows flow, troubleshooting, and
the `--no-herdr` / `--print-prompt` fallback paths, see
[WINDOWS_USAGE.md](WINDOWS_USAGE.md).

### Typical flow

```bash
cd ~/code/my-project
agent-init --bootstrap          # one-time: install herdr, firstmate, no-mistakes
agent-scan                      # generates .agent/repo-summary.md, architecture.md, ...
agent-check                     # validates the repo is in a buildable state
agent-review                    # builds the system prompt and prints it
agent-claude                    # launches claude with the prompt
```

### Multi-agent flow

```bash
cd ~/code/my-project
agent-fleet 3 --task code --wait                  # herdr backend (default): 3 panes, 3 worktrees
agent-fleet 3 --task code --backend treehouse     # treehouse backend: leased worktrees from the pool
agent-fleet 3 --task code --backend none          # no isolation; prompts only
```

The three backends:

- **`herdr` (default)** — uses `herdr worktree create` + `herdr agent start`. Best when you want each agent in its own terminal pane, attached to a live session.
- **`treehouse`** — uses `treehouse get --lease` to lease N pre-warmed worktrees from the pool. Best when you want cheap, reusable isolation; the worktrees return to the pool when the agent exits.
- **`none`** — writes N per-agent prompts to `.agent/SYSTEM_PROMPT.fleet-N.md` and tries to spawn N `claude` processes in the same checkout. Use only for testing; agents will collide on the working tree.

### Overnight flow

```bash
cd ~/code/my-project
echo "Fix all typecheck warnings in src/" > overnight-task.md
agent-overnight --task-file overnight-task.md
```

`agent-overnight` wraps `gnhf` with safe defaults: `--worktree` (isolated
branch), `--max-iterations 50`, `--max-tokens 100000`, and a preflight
check that refuses to run on a dirty repo. By morning, the
`gnhf/<slug>` branch has up to 50 commits, each addressing one warning.

### Choosing a model

`agent-claude` honours, in order:

1. `--model minimax-m3:cloud` (CLI override)
2. `AGENT_MODEL` environment variable
3. `agent-workbench/config.toml` in the install root
4. Built-in default `minimax-m3:cloud`

The runner (`claude`, `herdr agent start`, or `ollama run`) is picked
automatically: `agent-claude --backend auto` prefers herdr (when
installed) so the agent runs in an isolated pane.

## Dependencies

`agent-init` will optionally install the external tools the workbench
is designed to orchestrate. By default, `--bootstrap` installs:

| Tool | Why | Install source |
| --- | --- | --- |
| `herdr` | Agent multiplexer (`agent-runtime` role; default backend for `agent-fleet`) | `https://herdr.dev` |
| `firstmate` | Multi-agent orchestrator harness (`orchestrator` role; cloned to `~/firstmate`; shim at `~/.local/bin/firstmate`). Upstream ships a `bin/fm-*.sh` toolbelt, not a `firstmate doctor` / `test` / `build` CLI. | `github.com/kunchenguid/firstmate` |
| `no-mistakes` | Pre-push validation gate (`validation-gate` role; `agent-check` invokes `no-mistakes doctor` + `no-mistakes status`) | `github.com/kunchenguid/no-mistakes` |
| `treehouse` | Per-agent worktree pool (`isolation-manager` role; opt-in via `--bootstrap=treehouse`) | `github.com/kunchenguid/treehouse` |
| `lavish-axi` | Visual collaboration tool (`visual-collaboration` role; opt-in: `agent-init --bootstrap=lavish-axi`) | `github.com/kunchenguid/lavish-axi` |

Plus the model runtime: `claude` (Claude Code CLI) or `ollama` (local
fallback), and the terminal: `wezterm` (fallback when herdr's mux is
unwanted). See `tools/roles.md` for the full role mapping.

Re-run with `--no-bootstrap` to skip, or `--bootstrap=herdr,firstmate`
to scope. `agent-bootstrap` is also available as a standalone command
with the same flags (`--check`, `--all`, `--no-curl`, `--json`).

## Project instructions

Drop any of these into the repository root and they will be picked up automatically:

- `AGENTS.project.md`
- `CLAUDE.md`
- `docs/agent-rules/*.md`

## Supported operating systems

- Windows 10 / 11 — PowerShell 5.1+ and PowerShell 7+ (the installer also
  drops bash shims alongside the .ps1 shims, so `agent-init`, `agent-go`,
  etc. resolve in Git Bash and WSL on Windows without a separate profile)
- Linux (any distribution with Python 3.10+)
- WSL (treat as Linux; the bash shims are the primary install)
- Docker (Debian/Ubuntu/Alpine base images)

## Supported technologies

`.NET`, `WSO2 MI`, `Blazor`, `React`, `Angular`, `Node.js`, `Python`, `Java`, `Docker`, `MySQL`. Profiles are plain Markdown and can be added without code changes.

## Troubleshooting

### PowerShell blocks the script

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### `agent-claude` cannot find a model runner

The workbench looks for, in order: `claude` (Claude Code CLI), then
`herdr agent start` (when herdr is installed), then `ollama run
<model>`. Install one of:

- `npm install -g @anthropic-ai/claude-code`
- `irm https://herdr.dev/install.ps1 | iex` (Windows preview) or
  `curl -fsSL https://herdr.dev/install.sh | sh` (macOS/Linux)
- `winget install Ollama.Ollama` (Windows) or
  `curl -fsSL https://ollama.com/install.sh | sh` (macOS/Linux)

Or just run `agent-init --bootstrap=claude` to install the default.

### Symlink permission denied on Windows

`agent-init.ps1` will fall back to copying the scripts into `%USERPROFILE%\.local\bin\`. Add that directory to your `PATH` if it is not already.

### Wrong model loaded

Check the resolution order above. `agent-claude --model <name>` always wins.

## Contributing

1. Fork and branch.
2. Keep business logic in `scripts/python/`. Shell wrappers must stay thin.
3. Add new technology profiles as Markdown under `profiles/`.
4. Update `CHANGELOG.md` under the "Unreleased" section.
5. Open a pull request describing the user-visible change.

## Roadmap

- Profile auto-generation from a repository's first commit history.
- VS Code task integration.
- Optional pre-commit hook that runs `agent-check`.
- Multi-model routing (different models per task type).

## License

MIT. See `LICENSE`.
