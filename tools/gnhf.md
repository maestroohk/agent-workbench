# gnhf

A "ralph / autoresearch"-style orchestrator that keeps your agents
running while you sleep — each iteration makes one small, committed,
documented change towards an objective. Written by the same author as
`firstmate`, `no-mistakes`, and `treehouse`.

## Purpose

- Run a single command (`gnhf "<prompt>"`) that loops an agent
  (Claude Code, Codex, Copilot, Pi, Rovo Dev, OpenCode, or ACP
  targets) inside a Git repo.
- Each successful iteration is committed; failures are rolled back or
  preserved for repair.
- Runtime caps: `--max-iterations`, `--max-tokens`, `--stop-when`.
- Exponential backoff on retryable errors; abort after 3 consecutive
  failures.
- Worktree mode for parallel runs.
- Live-branch mode with optional auto-push.
- Ends with a permanent exit summary of branches, tokens, and diffs.

## Where it provides value in an AI workflow

- Long-running overnight tasks. "Good night, have fun" → wake up to a
  branch with N commits, each documented.
- Iterative improvement of a single objective, with the orchestrator
  handling the bookkeeping.

## Installation

- npm (recommended): `npm install -g gnhf`
- From source: `git clone https://github.com/kunchenguid/gnhf`,
  then `corepack enable && pnpm install && pnpm run build && pnpm
  link --global`
- `GNHF_TELEMETRY=0` to opt out of anonymous usage telemetry (no
  prompts, paths, or branch names are sent).

## Recommended usage

- One-off overnight: `gnhf "fix all the warnings in the type checker"`
- Capped run: `gnhf --max-iterations 50 --max-tokens 100000 "<prompt>"`
- Stop on a marker: `gnhf --stop-when "All TODOs are resolved"`

## Best practices

- Keep the prompt focused. "Fix everything" is a worse prompt than
  "Fix all `clippy::needless_borrow` warnings in `src/`."
- Use `--worktree` to keep the run isolated from your main checkout.
- Cap iterations and tokens; an unbounded loop will eat your quota.

## Integration with `agent-workbench`

- `agent-init --bootstrap=gnhf` installs it via npm.
- Out of scope for the first round of `agent-workbench` integration,
  but the install is wired up so future `agent-overnight` or similar
  commands can shell out to it.

## Limitations

- Iterative, not transformative. The agent makes small committed
  changes; sweeping refactors should be designed upfront.
- Telemetry is opt-out (set `GNHF_TELEMETRY=0`). The default is
  on. The data is anonymous (no prompts, paths, branch names).

## References

- Source: <https://github.com/kunchenguid/gnhf> (MIT, 2.9k stars)
- Latest: `gnhf: v0.1.42` (May 2026)
- Companion tools: `firstmate`, `no-mistakes`, `treehouse`
