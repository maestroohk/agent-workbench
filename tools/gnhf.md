# gnhf

`git-not-here-fixer`. A focused Git recovery tool for the cases that cause real damage: lost commits, dropped stashes, accidental resets, force-pushes.

## Purpose

- Recover work the user thought was gone. Not a substitute for understanding Git; a safety net for the cases where the user did not.
- Surface dangling commits, orphaned stashes, and reflog entries that would otherwise need a Stack Overflow search.
- One command: `gnhf save` snapshots, `gnhf list` shows recoverable work, `gnhf restore <id>` brings it back.

## Where it provides value in an AI workflow

- Agents sometimes overreach: a bad `git reset --hard`, a force-push, a `git stash` that ate work. `gnhf` provides a recovery path.
- Worth running once per session, before destructive operations, and on demand after something goes wrong.

## Installation

- macOS / Linux: `brew install gnhf` or `curl -sSf https://gnhf.dev/install.sh | sh`
- Windows: download the binary from <https://gnhf.dev/releases> or install under WSL.
- Per-project: not required. `gnhf` reads the local repository.

## Recommended usage

- Before any destructive operation: `gnhf snapshot "before force-push"`.
- When something has gone wrong: `gnhf list --since 1d`.
- Restore: `gnhf restore <id>`.

A typical recovery flow:

```bash
gnhf list
# 2026-07-05T14:22:11  abc1234  (before-reset)  main@{0}
gnhf restore abc1234 --into-branch recovery-2026-07-05
```

## Best practices

- `gnhf` is a safety net, not a workflow. Push branches and tag releases; do not lean on `gnhf` for the team's only durable history.
- Periodically prune `gnhf`'s local store if it grows large. It is local-only.
- Add a pre-commit hook that warns when about to do a force-push on a branch with unmerged work.

## Integration with `agent-workbench`

- Call `gnhf snapshot` from `agent-review` before the agent proposes a force-push.
- The agent can offer `gnhf restore` as a recovery path when explaining a failure.

## Limitations

- Local-only. Once the `.git` directory is destroyed and unrecoverable, `gnhf` cannot help.
- Not a backup tool. Use it for accidents, not for routine backups.
- Recovery from a force-push to a shared branch only works if at least one local clone still has the old commits.
