# kunchenguid companion tools

Three of the external tools the workbench orchestrates come from the
kunchenguid GitHub account. They're all MIT-licensed, cross-platform,
and built to be wired into agent workflows.

| Tool | Role | Where it fits in agent-workbench |
| --- | --- | --- |
| `no-mistakes` | Local Git proxy that pre-validates with review/test/docs/lint before pushing | `agent-check` surfaces its health; once you run `no-mistakes init` in a repo, every `git push` is intercepted |
| `treehouse` | Pool of reusable git worktrees for parallel agent workflows | `agent-fleet --backend treehouse` leases N pre-warmed worktrees from the pool |
| `gnhf` | "Good night, have fun" — autonomous agent loop with iteration / token caps | `agent-overnight "fix the warnings"` runs gnhf with safe defaults before you go to bed |

## Typical flows

### Pre-push validation with no-mistakes

```bash
cd your-repo
no-mistakes init                # one-time: sets up the local bare-repo gate
# ...work as usual, the workbench's AGENTS.md / global rules still apply...
git push                        # no-mistakes intercepts and runs review/test/docs/lint first
```

If no-mistakes fails the gate, the push is rejected and the validation
log is left in `.no-mistakes/` for you to inspect. Use
`no-mistakes status` to see the current run; `no-mistakes doctor` to
verify system health (the workbench's `agent-check` calls both).

### Multi-agent fleet with treehouse

```bash
cd your-repo
treehouse init                  # one-time: creates treehouse.toml
agent-fleet 3 --task code --backend treehouse --wait
```

Each agent gets its own worktree leased from the pool
(`~\.treehouse\<repo>-<hash>\<n>\<repo>`). When the agent exits, the
worktree returns to the pool with the build cache intact. Use
`treehouse status` to see the current pool; `treehouse prune` to
garbage-collect (dry-run by default).

### Overnight autonomous loop with gnhf

```bash
cd your-repo
agent-overnight "fix all typecheck warnings in src/"
```

The wrapper adds `--worktree` (isolated branch), `--max-iterations 50`,
and `--max-tokens 100000` so an unbounded loop can't eat your quota.
By morning, the `gnhf/<slug>` branch has up to 50 commits, each
addressing one warning. Use `--stop-when` to end on a marker string
the agent reports.

If you want the prompt to live in version control (recommended for
re-runnable overnight tasks), drop it in `overnight-task.md` and pass
`--task-file overnight-task.md` instead of the positional argument.

## How the workbench detects them

The workbench probes each tool by looking for its binary on `PATH` after
`agent-init --bootstrap` (or `agent-bootstrap` standalone). The
installers are:

- `no-mistakes` — downloaded from the latest GitHub release
  (zip on Windows, tar.gz on macOS/Linux); placed in `~/.local/bin/`.
- `treehouse` — same: GitHub release asset, extracted to `~/.local/bin/`.
- `gnhf` — installed via `npm install -g gnhf` (it's a Node CLI).

After `agent-init --bootstrap=gnhf,no-mistakes,treehouse`, all three
should report `present: yes` in `agent-bootstrap --check --json`.

## What the workbench does NOT do for you

- It does not auto-initialize the no-mistakes gate in a repo. You run
  `no-mistakes init` once per repo, and the gate then intercepts
  pushes. The workbench only surfaces health and status.
- It does not auto-start the treehouse pool. `agent-fleet
  --backend treehouse` leases on demand. The pool itself fills up
  the first time you (or an agent) `cd` into a worktree.
- It does not auto-run gnhf. `agent-overnight` is explicit; the
  workbench never kicks off an autonomous loop without you saying so.

## References

- `no-mistakes` — <https://github.com/kunchenguid/no-mistakes> (MIT, latest `v1.31.2`)
- `treehouse` — <https://github.com/kunchenguid/treehouse> (MIT, latest `v2.0.0`)
- `gnhf` — <https://github.com/kunchenguid/gnhf> (MIT, latest `gnhf-v0.1.42`)
- Companion tools by the same author: `firstmate`, `lavish-axi`
