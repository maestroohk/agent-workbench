# no-mistakes

A local git proxy that sits in front of your real remote. Its slogan:
"git push no-mistakes" — push to the `no-mistakes` remote, and a
disposable worktree runs the full review → test → docs → lint → push →
PR → CI pipeline before forwarding the branch. Written by the same
author as `firstmate`, `treehouse`, and `gnhf`.

## Purpose

- Catch off-by-one, wrong-type, misnamed-identifier, and
  order-of-operations issues statically, **plus** a full agent-driven
  review pass.
- Produce a short, actionable report. No false-positive floods.
- Plug into pre-commit and CI without ceremony — and as a side effect
  of `git push`, so the human's workflow is unchanged.

## Where it provides value in an AI workflow

- AI agents produce code quickly. They also produce mistakes quickly.
  `no-mistakes check` is a fast pre-flight check that catches the kind
  of bugs a careful human reviewer would flag in seconds.
- Useful as a guard rail before `agent-review` is invoked. The lint
  narrows the surface area; the agent review focuses on design.
- For the workbench, the `no-mistakes check` step in `agent-check` is
  the cheap pre-flight; the full `git push no-mistakes` flow runs the
  whole validation pipeline as a one-shot pre-PR gate.

## Installation

- macOS / Linux:
  `curl -fsSL https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh | sh`
- Windows (PowerShell):
  `irm https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.ps1 | iex`
- `go install github.com/kunchenguid/no-mistakes@latest`
- From source: `git clone` + `make install`

Verify with `no-mistakes --version`.

Per-project setup: `no-mistakes init` adds a `.no-mistakes.toml` and
the `no-mistakes` git remote.

## Recommended usage

- Run in pre-commit: `no-mistakes check --staged`.
- Run in CI on every PR: `no-mistakes check --all`.
- Push to `no-mistakes` (not `origin`) for the full pipeline:
  `git push no-mistakes <branch>`.
- Configure strictness per language. Turn off rules that fire on false
  positives in your codebase.

A minimal config:

```toml
[rules]
off-by-one = "error"
unreachable-code = "error"
unsafe-eval = "error"
naming-mismatch = "warn"
```

## Best practices

- Start with the default rule set. Add or remove rules based on actual
  findings, not on a theoretical preference.
- If a rule fires too often in CI, the rule or the codebase has a
  problem. Do not paper over it by turning the rule off without an
  entry in the config explaining why.
- Combine with language-native formatters (`dotnet format`, `gofmt`,
  `prettier`). `no-mistakes` is not a formatter.

## Integration with `agent-workbench`

- `agent-check` calls `no-mistakes check --all` when the binary is on
  `PATH`. `agent-check --no-no-mistakes` skips it.
- For agent-generated code, run `agent-check` before any commit; the
  workbench treats no-mistakes failures as errors.

## Limitations

- Not a replacement for tests, type checking, or human review.
- Some checks are language-specific. Coverage of newer languages lags.
- Configuration drift is real. Keep `.no-mistakes.toml` in version
  control.
- The full `git push no-mistakes` pipeline is heavyweight (it runs a
  full review agent). Prefer `no-mistakes check --all` for the
  iteration loop and the push-pipeline for the final gate.

## References

- Source: <https://github.com/kunchenguid/no-mistakes> (MIT, 5.3k stars)
- Install guide: <https://kunchenguid.github.io/no-mistakes/start-here/installation/>
- Latest release: `v1.31.2` (Jun 2026)
