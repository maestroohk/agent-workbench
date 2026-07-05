# lavish-axi

A long-running, opinionated AI orchestration daemon. Listens to file-system events, runs project commands, and exposes a small HTTP API for other tools (including AI agents) to query and trigger workflows.

## Purpose

- Project-level event bus. "When the `.cs` file changes, run `dotnet build`."
- A daemon that holds state across invocations: project index, last build result, last test run, dependency graph.
- An HTTP API other tools can hit. The agent does not need to know the project's command set; it asks the daemon.

## Where it provides value in an AI workflow

- The agent gets a structured view of the project: what changed, what depends on what, what passed, what failed. It does not have to re-derive this every prompt.
- Triggers: the daemon can run tests on save, then expose the result to the agent.
- Long-lived context: build cache, test cache, file index, all warm.

## Installation

- macOS / Linux: `curl -sSf https://lavish-axi.dev/install.sh | sh`
- Windows: download the installer from <https://lavish-axi.dev/releases> or run under WSL.
- Start: `lavish-axi start`. Stop: `lavish-axi stop`. Status: `lavish-axi status`.

## Recommended usage

- Run as a per-user background service: `lavish-axi start --user`.
- Add a `lavish-axi.toml` to the project to declare triggers:

```toml
[project]
name = "my-api"

[triggers.on-save]
paths = ["src/**/*.cs"]
run = "dotnet build"

[triggers.on-test]
run = "dotnet test"
report = "http://localhost:7474/results"
```

- Query: `curl http://localhost:7474/project/my-api/status | jq`.

## Best practices

- Treat the daemon's index as a cache. It is allowed to be wrong, briefly. Rebuild on corruption.
- Keep the trigger set small. A trigger that fires on every keystroke is a trigger that wastes the developer's time.
- Expose the daemon only on localhost unless you have a reason to do otherwise. It has project knowledge.

## Integration with `agent-workbench`

- `agent-claude` can query `lavish-axi` for project status before generating a system prompt. The prompt will include "what just changed" and "what just failed" without the agent re-running anything.
- `agent-test` can defer to the daemon's last-known test result if it is recent enough.

## Limitations

- Adds another long-running process to the developer's machine. Memory and CPU are real.
- The protocol is young; integrations are not yet a given.
- On Windows, WSL is the path of least resistance. Native support exists but lags.
- Do not expose the daemon to the network. It is not designed for it.
