#!/usr/bin/env bash
# agent-workbench one-line installer for macOS / Linux / WSL / Git Bash.
#
# Paste this in any shell on a clean machine:
#
#   curl -fsSL https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.sh | sh
#
# What it does:
#   1. Clones https://github.com/maestroohk/agent-workbench into
#      $HOME/.agent-workbench (or uses an existing checkout).
#   2. Runs agent-init which:
#        - symlinks the eight helper shims into $HOME/.local/bin
#        - bootstraps claude, herdr, firstmate, no-mistakes, treehouse,
#          gnhf, ollama, wezterm via brew / apt / curl-piped installer
#        - writes the agent-workbench-home marker file so the shims
#          resolve back to the toolkit root from .local/bin
#   3. Prints the export line the user should add to their shell rc;
#      does NOT edit profile files. (Use `agent-init --print-path`
#      to re-print it later.)
#   4. Prints the next step: `cd <your repo>; agent-go`.
set -euo pipefail

REPO_URL='https://github.com/maestroohk/agent-workbench.git'
INSTALL_ROOT="${HOME}/.agent-workbench"
BIN_DIR="${HOME}/.local/bin"

say() { printf '\033[36m[agent-workbench]\033[0m %s\n' "$*"; }

say "install root: ${INSTALL_ROOT}"
say "shim dir:     ${BIN_DIR}"

# 1. Clone (or update) the toolkit.
if [ ! -f "${INSTALL_ROOT}/scripts/python/dispatch.py" ]; then
    if [ -d "${INSTALL_ROOT}" ]; then
        say "removing stale ${INSTALL_ROOT} (no dispatch.py found)"
        rm -rf "${INSTALL_ROOT}"
    fi
    say "cloning ${REPO_URL}"
    git clone "${REPO_URL}" "${INSTALL_ROOT}"
else
    say "existing checkout found; pulling latest"
    (cd "${INSTALL_ROOT}" && git pull --ff-only) || say "pull failed (offline?); continuing with the existing checkout"
fi

# 2. Pick python and run agent-init.
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    say "python3 is required"
    exit 127
fi
export AGENT_WORKBENCH_HOME="${INSTALL_ROOT}"
export PYTHONPATH="${INSTALL_ROOT}/scripts/python:${PYTHONPATH:-}"
"${PY}" "${INSTALL_ROOT}/scripts/python/dispatch.py" init --bootstrap=all

# 3. Print the export line the user should add to their shell rc.
#    We do NOT edit ~/.bashrc, ~/.zshrc, or any other profile file.
#    Session-only PATH is still set on the next line so the rest of
#    the installer (and any tools the user runs in this session) can
#    see the shims.
export PATH="${BIN_DIR}:${PATH}"

_rc_path() {
  case "${SHELL:-}" in
    */zsh)  printf '%s' "${HOME}/.zshrc" ;;
    */bash) printf '%s' "${HOME}/.bashrc" ;;
    */fish) printf '%s' "${HOME}/.config/fish/config.fish" ;;
    *)      printf '%s' "${HOME}/.bashrc (or your shell's rc file)" ;;
  esac
}

if ! printf '%s' "${PATH}" | tr ':' '\n' | grep -qx "${BIN_DIR}"; then
  say ""
  say "add ${BIN_DIR} to your PATH for future shells by adding this line"
  say "to $(_rc_path):"
  say ""
  say "    export PATH=\"${BIN_DIR}:\$PATH\""
  say ""
fi

# 4. Next step.
say ""
say "all set. Try it on any repo:"
say "    cd /path/to/your/repo"
say "    agent-go"
