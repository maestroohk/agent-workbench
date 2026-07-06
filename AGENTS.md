# AGENTS.md

Global instructions for every AI coding agent interacting with this toolkit.

Load this file first. Project- and profile-specific instructions extend it; never replace it.

---

## 1. Engineering principles

1. Prefer production-quality code over draft-quality code.
2. Prefer maintainable solutions over clever ones.
3. Inspect existing code before editing it. Read enough to understand intent.
4. Make incremental changes. Small, reviewable diffs beat sweeping rewrites.
5. Never redesign architecture unless the user explicitly asks for it.
6. Never invent missing APIs, tables, DTOs, endpoints, business rules, configuration keys, or services.
7. Preserve existing behaviour unless change is requested and justified.
8. Explain assumptions when they materially affect the outcome.
9. Keep documentation concise and useful — not aspirational.
10. Avoid unnecessary abstractions. Three similar lines beat a premature helper.
11. Prefer readable code. Names should carry meaning; types and signatures should carry structure.

---

## 2. Code style

- Do not add comments to code unless explicitly requested.
- Do not generate comment-heavy code.
- Prefer expressive naming over comments.
- Only add comments when documenting a non-obvious business rule, external constraint, or workaround that is not visible from the code itself.
- Match the comment density, naming, and idiom of the surrounding code in any file you edit.

---

## 3. Change discipline

- Touch only what the task requires. Do not reformat unrelated lines.
- When refactoring, keep behaviour identical and call out the change in the summary.
- When a request is ambiguous, state the interpretation you adopted before producing code.
- When a request would break public contracts, surface the impact before proceeding.

---

## 4. Output discipline

- Reference code as `path:line` so it is navigable.
- Quote exact error messages, stack traces, and command output when reporting a problem.
- Distinguish "verified" from "inferred" in any status report.
- Never claim a command succeeded if you did not observe its output.

---

## 5. Tool use

- Prefer the dedicated file/search tools over shell equivalents.
- Use background processes for long-running commands; do not poll.
- Read a file before editing it. The harness enforces this; obey it.
- Keep destructive operations gated by confirmation unless explicitly authorised.

---

## 6. Failure handling

- If a test fails, report it with the actual output — do not paper over it.
- If a step is skipped, say so and why.
- If you cannot finish a task, leave the work in a state the user can resume, and document the gap.

---

## 7. Boundaries

- Do not push to remote repositories unless explicitly instructed.
- Do not publish packages, open pull requests, or send messages on the user's behalf.
- Do not modify global system state, dotfiles, or PATH outside the installer's documented scope.
- Do not silently modify `~/.bashrc`, `~/.zshrc`, PowerShell profile, user PATH, or Git config. If a persistent change is needed, ask first.

## 8. Roles and the workflow

The workbench orchestrates external tools, each filling a specific **role** at a specific point in the workflow. The roles are stable; the tools that fill them can change. `axi` is a design philosophy for agent-native CLIs (concise, structured, low-token); it is not a tool and not a dependency. The full mapping is in `tools/roles.md`; the short version:

- `orchestrator` — firstmate. Top-level coordination for multi-agent work.
- `visual-collaboration` — lavish-axi. Plans, mockups, diagrams, summaries.
- `isolation-manager` — treehouse. Per-agent worktree pool.
- `validation-gate` — no-mistakes. Pre-push review/test/lint gate.
- `overnight-runner` — gnhf. Long-running autonomous loops. NOT for normal interactive tasks.
- `agent-runtime` — herdr. Multiplexer for panes and worktrees.
- `model-runtime` — claude (default) or ollama (fallback). The actual model runner.
- `terminal-fallback` — wezterm. Optional GPU terminal.

The 9-step workflow a session follows, with the role in parens on each step:

1. Bootstrap / install prerequisites (`agent-runtime` + `model-runtime` + `validation-gate` + `orchestrator`).
2. Verify PATH / tool availability without silently editing shell profiles.
3. Scan the target repo and generate concise `.agent/` context (`agent-scan`).
4. Create a visual plan with lavish-axi when the task is complex or UI-related (`visual-collaboration`).
5. Use firstmate to delegate work to specialized agents (`orchestrator`).
6. Use treehouse for isolated worktrees for agent tasks (`isolation-manager`).
7. Run project tests / checks (`model-runtime` + `agent-test`).
8. Run no-mistakes as the final validation gate (`validation-gate`).
9. Produce a concise final report — preferably with lavish-axi if visual review is useful.

See `tools/roles.md` for the full table and rationale.
