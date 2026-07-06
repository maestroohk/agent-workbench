# firstmate

A per-project command orchestrator. Replaces the per-project README's
"How to run things" section with an executable interface. Written by the
same author as `no-mistakes`, `treehouse`, and `gnhf`.

## Purpose

- `firstmate test`, `firstmate build`, `firstmate lint`, `firstmate run`
  — regardless of whether the project uses `dotnet`, `npm`, `mvn`, or
  `go test` under the hood.
- A `firstmate.toml` declares the commands once, in one place. CI,
  developers, and AI agents all read from the same source of truth.
- Reduces the "how do I run the tests for this project" question to one
  command.
- Beyond a single CLI, firstmate is a multi-agent harness: it dispatches
  a single user request to multiple "crewmate" agents in parallel, each
  on its own worktree, and reconciles their results. The crewmate
  pattern is the same one `agent-fleet` exposes for one-shot use.

## Where it provides value in an AI workflow

- The agent does not need to guess the project's command set.
  `firstmate test` works everywhere.
- Consistent logging and exit codes mean the agent can detect success
  and failure the same way across projects.
- Less hand-written glue in `agent-test`: when a `firstmate.toml` is
  present, `agent-test` shells out to `firstmate test` directly.

## Installation

firstmate is a directory + `AGENTS.md` harness, **not** a CLI binary.
Install by cloning the repo and launching Claude Code inside it:

```bash
gh auth login
git clone https://github.com/kunchenguid/firstmate
cd firstmate
claude                  # launches the harness; AGENTS.md takes over
```

The first mate agent itself detects and offers to install everything
else (treehouse, no-mistakes, etc.). For the workbench, the
`firstmate.toml` in the project being checked is what matters; the
firstmate harness is what runs the commands.

The workbench probes for firstmate by checking (in order):

1. `firstmate` is on `PATH` (a binary shim placed there by the firstmate
   installer, or a manual alias).
2. `~/firstmate/AGENTS.md` exists (the harness directory).
3. The project has a `firstmate.toml` in its root.

If any of these is true, `agent-test` will use `firstmate test` and
`agent-check` will use `firstmate doctor` / `firstmate build`.

## Recommended usage

- Commit `firstmate.toml` to the repository.
- Wire CI to call `firstmate ci`, which fans out to test, lint, and
  build.
- Document once: "Run `firstmate test` to test."

A minimal config:

```toml
[project]
name = "my-api"

[commands.test]
run = "dotnet test -c Release"
description = "Run the test suite"

[commands.build]
run = "dotnet build -c Release"
description = "Build the project"

[commands.lint]
run = "dotnet format --verify-no-changes"
description = "Verify formatting"
```

## Best practices

- Commands should be one logical step. Compose them in CI, not in
  `firstmate.toml`.
- Keep `description` short. It is what the agent sees in `--help`.
- Use `firstmate doctor` to detect missing toolchains before the first
  command runs.

## Integration with `agent-workbench`

- `agent-test` calls `firstmate test` when firstmate is detected.
  `agent-test --firstmate` forces this path; `agent-test --no-firstmate`
  skips it.
- `agent-check` calls `firstmate doctor` and `firstmate build` when
  firstmate is detected. `agent-check --no-firstmate` skips them.
- For one-shot multi-agent dispatch, prefer `agent-fleet N` (which
  uses herdr underneath); firstmate's crewmate pattern is for
  long-running projects where the captain pattern fits the workflow.

## Limitations

- Another layer between the developer and the toolchain. If the
  toolchain's native CLI is good and stable, `firstmate` adds little.
- Plugins for less-common build systems are limited.
- A wrong entry in `firstmate.toml` will fail every consumer — humans
  and agents alike. Keep the file under review.
- firstmate is a Node/Bash-heavy setup; the workbench treats it as
  optional. Projects without `firstmate.toml` work exactly as they did
  before this integration.

## References

- Source: <https://github.com/kunchenguid/firstmate> (MIT)
- Readme: <https://github.com/kunchenguid/firstmate#readme>
- Required harness: any of `claude`, `codex`, `opencode`, `pi`, `grok`
  (the first mate is launched by one of these)

> **Note on `agent-check`.** As of 2026-07-06, `agent-check` does not
> call `firstmate doctor` or `firstmate build` — those subcommands do
> not exist upstream. Instead it reports the harness's install path,
> the most recent commit, the shim resolution, and a count of
> `bin/fm-*.sh` scripts. See `CHANGELOG.md` [Unreleased] for the
> change history.
