# treehouse

A project-isolated development environment manager. Spawns shell sessions, Docker containers, or remote workspaces per project, with consistent environment variables and tooling.

## Purpose

- One shell, one environment, one project. No more `source .envrc` rituals.
- Reproducible dev environments: a `treehouse.toml` declares what the project needs (language version, env vars, services, ports).
- Switch between projects without leaking environment state.

## Where it provides value in an AI workflow

- The agent is invoked in a shell. If the shell is in the wrong environment, the agent gets the wrong toolchain. `treehouse` guarantees the agent sees the same environment the developer does.
- Useful for projects with several services (Postgres + Redis + a backend). `treehouse up` brings the whole stack up; the agent can then reason about a running system rather than a cold one.

## Installation

- macOS / Linux: `curl -sSf https://treehouse.dev/install.sh | sh`
- Windows: install via WSL. Treehouse targets Unix-style shells.

## Recommended usage

- Run `treehouse init` in a new project to generate `treehouse.toml`.
- Use `treehouse enter` to start a session in the project's environment. Run `agent-scan` and `agent-claude` from inside that session.
- Use `treehouse up` for projects with Docker Compose dependencies.

A minimal `treehouse.toml`:

```toml
[project]
name = "my-api"
runtime = "python@3.12"

[env]
DATABASE_URL = "postgres://localhost/myapi"

[services.postgres]
image = "postgres:16"
port = 5432
```

## Best practices

- Commit `treehouse.toml` to the repository. It is the contract between the project and the developer's environment.
- Keep the file small. If it grows past 50 lines, the project's environment may be doing too much.
- Pair with `direnv` if your team has contributors who do not use treehouse.

## Integration with `agent-workbench`

- Run `agent-claude` from inside `treehouse enter`. The agent will see the right Python version, env vars, and services.
- Useful for WSL / Docker development where the host and the agent might otherwise disagree on which toolchain is current.

## Limitations

- Single-developer ergonomics. For team-wide environment enforcement, prefer Nix or devcontainers.
- Windows requires WSL.
- The ecosystem is younger than Nix or asdf; if you depend on exotic runtimes, evaluate first.
