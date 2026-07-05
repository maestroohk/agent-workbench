# firstmate

A project-level orchestrator that wraps your build, test, and lint commands behind a single CLI. Replaces the per-project README's "How to run things" section with an executable interface.

## Purpose

- `firstmate test`, `firstmate build`, `firstmate lint`, `firstmate run` — regardless of whether the project uses `dotnet`, `npm`, `mvn`, or `go test` under the hood.
- A `firstmate.toml` declares the commands once, in one place. CI, developers, and AI agents all read from the same source of truth.
- Reduces the "how do I run the tests for this project" question to one command.

## Where it provides value in an AI workflow

- The agent does not need to guess the project's command set. `firstmate test` works everywhere.
- Consistent logging and exit codes mean the agent can detect success and failure the same way across projects.
- Less hand-written glue in `agent-test`.

## Installation

- macOS / Linux: `brew install firstmate` or `curl -sSf https://firstmate.dev/install.sh | sh`
- Windows: download the binary from <https://firstmate.dev/releases> or `winget install firstmate`.
- Per-project: `firstmate init` generates a starter `firstmate.toml`.

## Recommended usage

- Commit `firstmate.toml` to the repository.
- Wire CI to call `firstmate ci`, which fans out to test, lint, and build.
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

- Commands should be one logical step. Compose them in CI, not in `firstmate.toml`.
- Keep `description` short. It is what the agent sees in `--help`.
- Use `firstmate doctor` to detect missing toolchains before the first command runs.

## Integration with `agent-workbench`

- `agent-test` calls `firstmate test`. `agent-check` calls `firstmate doctor` and `firstmate build`. The agent does not need to know the project's command set.
- This makes `agent-workbench` portable across projects without per-project configuration on the toolkit side.

## Limitations

- Another layer between the developer and the toolchain. If the toolchain's native CLI is good and stable, `firstmate` adds little.
- Plugins for less-common build systems are limited.
- A wrong entry in `firstmate.toml` will fail every consumer — humans and agents alike. Keep the file under review.
