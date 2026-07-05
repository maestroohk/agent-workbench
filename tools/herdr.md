# herdr

A terminal multiplexer rebuilt for AI coding agents. The default
multi-agent backbone for `agent-fleet`. Each pane is a real PTY; herdr
ships a built-in agent-state detector that watches the prompt for
Claude Code, Codex, OpenCode, Droid, Amp, Pi, Cursor Agent, Kimi, Copilot
CLI, Hermes, and more — surfacing a sidebar with 🔴 blocked / 🟡 working /
🔵 done / 🟢 idle.

## Purpose

- Run several coding agents in parallel, each in its own pane, and tell
  at a glance which one is blocked and which is finished.
- Spawn agents on fresh git worktrees so concurrent work does not
  collide on disk.
- Drive the whole thing from a CLI: `herdr agent start`, `herdr agent
  wait`, `herdr worktree create`, `herdr agent send` — all scriptable
  so the workbench can orchestrate without the GUI.
- The Claude Code integration (`herdr integration install claude`)
  registers a hook that reports agent state from inside Claude Code,
  with no agent-side glue.

## Where it provides value in an AI workflow

- `agent-fleet N` uses herdr to spawn N agents in N panes, each on its
  own worktree, and `agent-claude` (with `--backend=herdr`) does the
  same for the single-agent flow.
- Detach/reattach: close the laptop and the agents keep running; SSH
  back in and the panes are still there.
- Local Unix socket + CLI API so the agent itself (or the workbench)
  can drive other agents.

## Installation

- Windows (preview, recommended on Windows):
  `irm https://herdr.dev/install.ps1 | iex`
- macOS / Linux / WSL: `curl -fsSL https://herdr.dev/install.sh | sh`
- Homebrew: `brew install herdr`
- `mise use -g herdr`
- `nix run github:ogulcancelik/herdr`
- From source: `cargo install herdr`

Verify with `herdr --version`. The daemon is a single binary at
`~/.local/bin/herdr` (or `%USERPROFILE%\.local\bin\herdr.exe` on
Windows).

After install, run once interactively (`herdr`) so the server can
create its initial state directory.

## Claude Code integration

```bash
herdr integration install claude
```

This writes a hook to `~/.claude/hooks/herdr-agent-state.ps1` (or the
unix equivalent) and registers it in `~/.claude/settings.json`. After
this, Claude Code's state is reported to the herdr sidebar
automatically — no per-agent code required.

The workbench runs this step on first use of `--backend=herdr`.

## CLI surface the workbench uses

| Command | Why |
|---|---|
| `herdr status server` | probe whether the daemon is running |
| `herdr worktree create --label … --no-focus --json` | lease a worktree per agent |
| `herdr agent start <name> --cwd <wt> --tab new -- <argv…>` | launch the agent in a new pane |
| `herdr agent wait <name> --status done --timeout <ms>` | block until the agent finishes |
| `herdr agent list` | enumerate running agents |
| `herdr pane list` | enumerate panes (debug) |
| `herdr integration install claude` | one-time setup |

## Integration with `agent-workbench`

- `agent-claude` defaults to `auto` backend — when herdr is available
  and the `claude` CLI is on PATH, the agent runs in an isolated herdr
  pane on a fresh worktree.
- `agent-fleet` uses herdr as the primary multi-agent backend.
- `agent-init --bootstrap=herdr` installs it (curl-piped PowerShell on
  Windows; curl-piped bash on macOS/Linux).

## Best practices

- Detach with `Ctrl-b d` rather than closing the terminal. The server
  keeps panes alive.
- Use one worktree per agent. The `--no-focus` flag keeps the user's
  current pane active while agents start up.
- Set `HERDR_SOCKET_PATH` in your shell if you have multiple herdr
  instances; the CLI defaults to `~/.herdr/herdr.sock`.

## Limitations

- The Windows install is a preview build. The `herdr channel set
  stable` command is rejected on Windows until a stable release ships.
- AGPL-3.0-or-later license (with a commercial licence available).
  This is a runtime dependency for the workbench, not a build-time
  link, so the workbench itself stays MIT.
- The integration hook requires Claude Code to be installed before
  `herdr integration install claude` is run; otherwise the
  `~/.claude/settings.json` hook is registered but cannot fire.

## References

- Source: <https://github.com/ogulcancelik/herdr> (12k stars, AGPL-3.0)
- Site: <https://herdr.dev/>
- Install: <https://herdr.dev/docs/install/>
- Socket API: <https://herdr.dev/docs/socket-api/>
