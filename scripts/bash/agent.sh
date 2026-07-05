#!/usr/bin/env bash
# agent-workbench dispatcher.
# All business logic lives in scripts/python/. This wrapper only sets up the
# environment and invokes Python.
set -euo pipefail

# Resolve the directory containing this script, then the toolkit root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLKIT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_DIR="${TOOLKIT_ROOT}/scripts/python"
export AGENT_WORKBENCH_HOME="${TOOLKIT_ROOT}"
export PYTHONPATH="${PYTHON_DIR}:${PYTHONPATH:-}"

# Pick a Python interpreter. Prefer python3; fall back to python.
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo "error: python3 is required to run agent-workbench" >&2
  exit 127
fi

exec "${PYTHON_BIN}" "${PYTHON_DIR}/dispatch.py" "$@"
