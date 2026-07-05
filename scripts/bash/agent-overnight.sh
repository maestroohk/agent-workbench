#!/usr/bin/env bash
# agent-overnight: wrap gnhf with safe defaults for long autonomous runs.
exec "$(dirname "$0")/agent.sh" overnight "$@"
