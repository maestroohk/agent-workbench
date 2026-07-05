# WezTerm

A GPU-accelerated cross-platform terminal emulator with a Lua configuration. Works on Windows, macOS, and Linux.

## Purpose

- A modern terminal that replaces ConEmu, Hyper, iTerm2, or GNOME Terminal.
- Tabs, splits, and a multiplexer built in — no tmux required for basic session work.
- Lua configuration for layouts, key bindings, and per-project settings.

## Where it provides value in an AI workflow

- Reliable rendering of long, colour-rich output from models. WezTerm handles wide Unicode, ligatures, and inline images better than most terminals.
- A per-project layout that opens in one command. The `wezterm.lua` can read `.wezterm.lua` from the current working directory and configure itself.
- SSH multiplexing: one pane running on a remote box, one local, sharing the same shortcuts.

## Installation

- macOS: `brew install --cask wezterm`
- Windows: `winget install wez.wezterm` or download the installer from <https://wezfurlong.org/wezterm/>
- Linux: an AppImage is provided. Alternatively, install via your package manager if it carries it.

## Recommended usage

- A `~/.wezterm.lua` configuration that loads per-project overrides from `.wezterm.lua` in the working directory.
- Key bindings: keep muscle memory compatible with your editor. `Ctrl-Shift-e` to open the launcher, `Ctrl-Shift-w` to close a pane, `Alt-h/j/k/l` to navigate.
- Use `wezterm cli split-pane` for scripted layouts.

A minimal config:

```lua
local wezterm = require 'wezterm'
local config = wezterm.config_builder()

config.default_prog = { os.getenv 'SHELL' or 'cmd.exe' }
config.enable_tab_bar = true
config.window_padding = { left = 8, right = 8, top = 4, bottom = 4 }
config.color_scheme = 'Catppuccin Mocha'

return config
```

## Best practices

- Use `wezterm.image_from_file` to render images (screenshots, diagrams) inline. Useful when an agent pastes an image path.
- Use the `mux` subsystem if you want persistent sessions across reboots without bringing in tmux.
- Combine with `lazygit` for an excellent TUI git workflow inside WezTerm splits.

## Integration with `agent-workbench`

- Open a WezTerm window in the project root. Use a split for the editor and another for `agent-claude`. WezTerm keeps the agent pane scrollback.
- Configure per-project `.wezterm.lua` files for projects with non-standard layouts (Blazor, WSO2 MI dev server, etc.).

## Limitations

- Slightly higher memory and GPU usage than minimalist terminals (Alacritty, foot). Negligible on modern hardware.
- Lua configuration is powerful but is a real surface area. Keep your config in version control.
- The `mux` subsystem overlaps with tmux; pick one per project and stay consistent.
