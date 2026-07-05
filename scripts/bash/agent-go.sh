#!/usr/bin/env bash
# agent-go: one-liner cold-machine bootstrap.
#  - install missing tools (herdr, claude, firstmate, no-mistakes, treehouse, gnhf, ollama)
#  - start the herdr server in the background
#  - launch `claude` (or `ollama run`) with the assembled system prompt
exec "$(dirname "$0")/agent.sh" go "$@"
