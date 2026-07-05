# tmux

Terminal multiplexer. Long-lived sessions, split panes, scripted layouts.

## Purpose

- Keep a development session alive across SSH drops, sleep, and reboots.
- Run multiple long-lived processes (server, watcher, tests) in named panes and switch between them.
- Script repeatable window layouts for a project.

## Where it provides value in an AI workflow

- Launching the model and watching its output in one pane while you iterate in another.
- Pairing a long-running dev server with a watcher pane and a log pane, all in one named session per project.
- Detaching and reattaching the same working environment from any terminal (including WezTerm panes).

## Installation

- macOS: `brew install tmux`
- Debian / Ubuntu: `sudo apt install tmux`
- Fedora / RHEL: `sudo dnf install tmux`
- Windows: native `tmux` is not available. Use WSL. On Git Bash, tmux may be present as a separate install; prefer WSL for parity.

## Recommended usage

- One session per project: `tmux new -s <project>`.
- One window per concern: editor, server, tests, agent.
- Prefix key: leave the default `Ctrl-b` unless you have a strong reason to change it.
- Status line: keep it short. Project name, git branch, pane title.
- Mouse mode: enable it for casual use; disable it for scripted workflows.

A minimum config that works well:

```tmux
set -g mouse on
set -g base-index 1
setw -g pane-base-index 1
set -g default-terminal "tmux-256color"
bind r source-file ~/.tmux.conf \; display "reloaded"
```

## Best practices

- Name your sessions. Unnamed sessions are abandoned sessions.
- Use `tmux-resurrect` and `tmux-continuum` if you want sessions to survive reboots.
- Pair tmux with WezTerm: WezTerm handles tabs and splits at the terminal level; tmux handles sessions and the cross-machine story.

## Integration with `agent-workbench`

- `agent-claude` is a long-running process. Launch it in a named pane inside a project session.
- A typical four-pane layout: editor (Neovim), server, tests (auto-rerun), agent.

## Limitations

- Not native on Windows. WSL works; native does not.
- No GPU acceleration. For AI workloads that benefit from a real terminal emulator (Kitty, WezTerm, Ghostty), tmux is the wrong layer for graphics.
- Scrollback is in-memory by default. Use `set -g history-limit 100000` if you need more.
