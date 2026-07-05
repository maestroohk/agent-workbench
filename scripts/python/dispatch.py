"""Thin dispatcher invoked by the shell wrappers.

Each wrapper (`agent-init`, `agent-scan`, etc.) calls into this script with
the verb as the first argument. This keeps the wrappers free of logic
and ensures there is one place where command dispatch lives.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Force UTF-8 on stdout/stderr so non-ASCII characters (em-dashes, arrows,
# etc.) that appear in user-provided repo content or in our own messages
# do not crash on Windows consoles configured with cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


COMMANDS = {
    "init": "install",
    "scan": "scan_repo",
    "check": "agent_check",
    "review": "build_prompt",
    "test": "agent_test",
    "claude": "agent_claude",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="agent-workbench command dispatcher.")
    parser.add_argument("verb", choices=sorted(COMMANDS))
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    module_name = COMMANDS[args.verb]
    module = __import__(module_name)
    func = getattr(module, "main", None)
    if func is None:
        print(f"error: module {module_name} has no main()", file=sys.stderr)
        return 1
    return func(args.rest) or 0


if __name__ == "__main__":
    raise SystemExit(main())
