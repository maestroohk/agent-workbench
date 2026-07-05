# no-mistakes

A code-quality linter that catches common correctness bugs before they reach code review. Focuses on mistakes a human reviewer would catch but a regular linter would not.

## Purpose

- Catch off-by-one, wrong-type, misnamed-identifier, and order-of-operations issues statically.
- Produce a short, actionable report. No false-positive floods.
- Plug into pre-commit and CI without ceremony.

## Where it provides value in an AI workflow

- AI agents produce code quickly. They also produce mistakes quickly. `no-mistakes` is a fast pre-flight check that catches the kind of bugs a careful human reviewer would flag in seconds.
- Useful as a guard rail before `agent-review` is invoked. The lint narrows the surface area; the agent review focuses on design.

## Installation

- macOS / Linux: `curl -sSf https://no-mistakes.dev/install.sh | sh`
- Per-project: `no-mistakes init` adds a `.no-mistakes.toml` and pre-commit hook.
- Editor integrations: VS Code and Neovim plugins are available.

## Recommended usage

- Run in pre-commit: `no-mistakes check --staged`.
- Run in CI on every PR: `no-mistakes check --all`.
- Configure strictness per language. Turn off rules that fire on false positives in your codebase.

A minimal config:

```toml
[rules]
off-by-one = "error"
unreachable-code = "error"
unsafe-eval = "error"
naming-mismatch = "warn"
```

## Best practices

- Start with the default rule set. Add or remove rules based on actual findings, not on a theoretical preference.
- If a rule fires too often in CI, the rule or the codebase has a problem. Do not paper over it by turning the rule off without an entry in the config explaining why.
- Combine with language-native formatters (`dotnet format`, `gofmt`, `prettier`). `no-mistakes` is not a formatter.

## Integration with `agent-workbench`

- Run `no-mistakes check` as part of `agent-check`. Fail the check on errors, warn on warnings.
- Use it in pre-commit hooks so AI-generated code lands in the same shape as human-generated code.

## Limitations

- Not a replacement for tests, type checking, or human review.
- Some checks are language-specific. Coverage of newer languages lags.
- Configuration drift is real. Keep `.no-mistakes.toml` in version control.
