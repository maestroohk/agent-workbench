# treehouse

A pool of reusable git worktrees that AI agents (or humans) can lease
instantly, without cloning. Per-project checkout takes a few hundred
milliseconds; the worktree is preserved in the pool with the build
cache and dependencies intact. Written by the same author as
`firstmate` and `no-mistakes`.

## Purpose

- Drop into a clean worktree in one command, do work, exit. The
  worktree returns to the pool.
- Reusable worktrees — dependencies and build cache are kept warm.
- Detached HEAD mode by default, so concurrent agents on the same
  branch do not collide.
- In-use detection — treehouse scans running processes so two agents
  cannot grab the same worktree.
- Durable leases: `treehouse get --lease` reserves a worktree without
  opening a subshell.
- Safe pruning: dry-run by default; requires `--yes` to delete.

## Where it provides value in an AI workflow

- The workbench's `agent-fleet` uses treehouse (when herdr is
  unavailable) to lease N worktrees in parallel, one per agent.
- AI agents in parallel can each have a clean, isolated worktree
  without each agent paying the full checkout / build cost.

## Installation

- macOS / Linux: `curl -fsSL https://kunchenguid.github.io/treehouse/install.sh | sh`
- Windows (PowerShell): `irm https://kunchenguid.github.io/treehouse/install.ps1 | iex`
- Nix: `nix run github:kunchenguid/treehouse`
- `go install github.com/kunchenguid/treehouse@latest`
- From source: `git clone` + `make install`

Verify with `treehouse --version`.

## Recommended usage

- `treehouse get` — drop into a subshell in a fresh worktree. Exiting
  returns the worktree to the pool.
- `treehouse get --lease` — reserve a worktree without a subshell
  (used by `agent-fleet`).
- `treehouse list` — enumerate worktrees in the pool.
- `treehouse prune` — garbage-collect unused worktrees (dry-run by
  default; `--yes` to commit).

A minimal flow:

```bash
$ treehouse get
(worktree: ~/treehouse/pool/abc123) $ git status
HEAD detached at origin/main
$ exit
# worktree returned to the pool, build cache preserved
```

## Best practices

- Use detached HEAD mode unless the user explicitly needs a branch.
- Lease (`--lease`) when an external process will manage the worktree;
  only the subshell form opens an interactive shell.
- Prune periodically; the pool can grow without bound.

## Integration with `agent-workbench`

- `agent-fleet` uses treehouse as the fallback multi-agent backend
  when herdr is not available.
- The lease is short-lived: agents that finish within the timeout are
  reaped automatically; agents that exceed the timeout can be
  recovered manually with `treehouse list` + `treehouse prune`.

## Limitations

- Local-only state. Worktrees are not shared between machines.
- Detached HEAD means no automatic upstream tracking; if you need
  branches, pass `--branch` explicitly.
- Windows support is via the same `install.ps1` flow as the other
  kunchenguid tools; native installer is the same path.

## References

- Source: <https://github.com/kunchenguid/treehouse> (MIT, 740 stars)
- Releases: 20 releases; latest `v2.0.0` (Jun 2026)
- Companion tools by the same author: `firstmate`, `no-mistakes`,
  `gnhf`
