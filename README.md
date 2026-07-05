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
git clone https://github.com/<your-org>/agent-workbench.git
cd agent-workbench
.\scripts\powershell\agent-init.ps1
```

If your PowerShell execution policy blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then re-run.

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
| `agent-init`    | Install or update the toolkit                             |
| `agent-scan`    | Generate `.agent/` summaries for the current repository   |
| `agent-check`   | Validate the repository (structure, missing files)        |
| `agent-review`  | Print a review-ready system prompt for the repo           |
| `agent-test`    | Run the detected test suite, if any                       |
| `agent-claude`  | Launch the model with the assembled system prompt         |

### Typical flow

```bash
cd ~/code/my-project
agent-scan              # generates .agent/repo-summary.md, architecture.md, ...
agent-check             # validates the repo is in a buildable state
agent-review            # builds the system prompt and prints it
agent-claude            # launches ollama with the prompt
```

### Choosing a model

`agent-claude` honours, in order:

1. `--model minimax-m3:cloud` (CLI override)
2. `AGENT_MODEL` environment variable
3. `agent-workbench/config.toml` in the install root
4. Built-in default `minimax-m3:cloud`

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

### `agent-claude` cannot find ollama

Install Ollama from <https://ollama.com/download> and ensure `ollama --version` works in the same shell.

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
