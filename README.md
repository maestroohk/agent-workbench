# agent-workbench

A cross-platform AI development toolkit. One source of truth for global instructions, project rules, repository summaries, and the launch command for your preferred local model. Works on Windows 10/11, Linux, WSL, and Docker development containers.

## Goals

- Reusable global AI instructions that travel with the toolkit.
- Per-repository project instructions that are auto-discovered.
- Automatic repository scanning, stack detection, and prompt assembly.
- A single launcher that puts the right context in front of the model.
- Helper commands for the common workflows: init, scan, check, review, test.

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
PATH (no admin required), and bootstraps `claude`, `herdr`, `firstmate`,
`no-mistakes`, `treehouse`, `gnhf`, `ollama`, and `wezterm` — picking
the right install method per platform (winget, choco, npm, or the
project's own curl-piped installer).

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
| `agent-bootstrap` | Install external dependencies (herdr, firstmate, no-mistakes, treehouse) on demand |
| `agent-scan`    | Generate `.agent/` summaries for the current repository   |
| `agent-check`   | Validate the repository (structure, firstmate doctor, no-mistakes) |
| `agent-review`  | Print a review-ready system prompt for the repo           |
| `agent-test`    | Run the detected test suite, or `firstmate test` if firstmate is installed |
| `agent-claude`  | Launch Claude Code (or ollama) with the assembled system prompt |
| `agent-fleet`   | Spawn N Claude agents in parallel, each in an isolated herdr pane and worktree |

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

The other tools (`no-mistakes`, `gnhf`, `firstmate test`, `agent-fleet`)
are on PATH and used by Claude Code as needed.

### Typical flow

```bash
cd ~/code/my-project
agent-init --bootstrap          # one-time: install herdr, firstmate, no-mistakes, treehouse
agent-scan                      # generates .agent/repo-summary.md, architecture.md, ...
agent-check                     # validates the repo is in a buildable state
agent-review                    # builds the system prompt and prints it
agent-claude                    # launches claude with the prompt
```

### Multi-agent flow

```bash
cd ~/code/my-project
agent-fleet 3 --task code --wait   # spawns 3 agents in 3 herdr panes on 3 worktrees; waits
agent-fleet 1 --backend herdr     # spawn a single isolated agent
agent-fleet 2 --backend treehouse  # fall back to treehouse if herdr is unavailable
```

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
| `herdr` | Agent multiplexer (default backend for `agent-fleet`) | `https://herdr.dev` |
| `firstmate` | Per-project command orchestrator (`firstmate test` / `build` / `lint`) | `github.com/kunchenguid/firstmate` |
| `no-mistakes` | Pre-push validation (`agent-check` invokes `no-mistakes check --all`) | `github.com/kunchenguid/no-mistakes` |
| `treehouse` | Git worktree pool (fallback backend for `agent-fleet`) | `github.com/kunchenguid/treehouse` |

Plus the model runtime: `claude` (Claude Code CLI) or `ollama` (local
fallback), and the terminal: `wezterm` (fallback when herdr's mux is
unwanted).

Re-run with `--no-bootstrap` to skip, or `--bootstrap=herdr,firstmate`
to scope. `agent-bootstrap` is also available as a standalone command
with the same flags (`--check`, `--all`, `--no-curl`, `--json`).

## Project instructions

Drop any of these into the repository root and they will be picked up automatically:

- `AGENTS.project.md`
- `CLAUDE.md`
- `docs/agent-rules/*.md`

## Supported operating systems

- Windows 10 / 11 (PowerShell 5.1+ and PowerShell 7+)
- Linux (any distribution with Python 3.10+)
- WSL (treat as Linux)
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
