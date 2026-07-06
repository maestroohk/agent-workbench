# Roles and workflow

The workbench orchestrates a small set of external tools, each of which
fills a specific **role** at a specific point in the workflow. The roles
are stable; the tools that fill them can change. `axi` is a design
philosophy for agent-native CLIs (concise, structured, low-token); it
is not a tool and not a dependency.

| Role | Tool | Purpose | When in the workflow |
| --- | --- | --- | --- |
| `orchestrator` | `firstmate` | Multi-agent harness that dispatches a user request to multiple crewmate agents in parallel. | Step 5 — delegate work to specialized agents. |
| `visual-collaboration` | `lavish-axi` | Local-first HTML authoring tool for human + AI collaboration on plans, mockups, diagrams, comparison tables, final summaries. | Steps 4 and 9 — visual plan up front, visual summary at the end. |
| `isolation-manager` | `treehouse` | Pool of reusable git worktrees; `agent-fleet --backend treehouse` leases N pre-warmed worktrees from the pool. | Step 6 — before spawning agents, so parallel work does not corrupt the main checkout. |
| `validation-gate` | `no-mistakes` | Git proxy that pre-validates with review/test/docs/lint before pushing. `agent-check` calls `no-mistakes doctor` and `no-mistakes status`. | Step 8 — the final gate before push/PR. |
| `overnight-runner` | `gnhf` | Long-running autonomous loop driver. Each successful iteration is a separate commit; aborts on `--max-iterations` / `--max-tokens`. | NOT in the default 9-step workflow. Use `agent-overnight` when the user explicitly asks for overnight/background progress. |
| `agent-runtime` | `herdr` | Multiplexer for agent panes and worktrees. The default backend for `agent-fleet`. | Steps 5–6 — host for the agents. |
| `model-runtime` | `claude` (default) or `ollama` (fallback) | The actual model runner. | Steps 5–7 — what the agents call. |
| `terminal-fallback` | `wezterm` | GPU-accelerated terminal; an optional alternative to herdr's own mux. | Not on the hot path. Optional. |

## The 9-step workflow

After a clean install, this is the loop a session follows:

1. **Bootstrap / install prerequisites** (one-time, per machine). Role: `agent-runtime` + `model-runtime` + `validation-gate` + `orchestrator`.
2. **Verify PATH / tool availability** without silently editing shell profiles. The workbench never modifies `~/.bashrc`, `~/.zshrc`, PowerShell profile, or HKCU PATH without explicit consent; the install scripts prompt before persisting. Role: any installed tool.
3. **Scan the target repo and generate concise `.agent/` context** with `agent-scan`. Role: any.
4. **Create a visual plan with lavish-axi** when the task is complex or UI-related. Skipped for trivial work. Role: `visual-collaboration`.
5. **Use firstmate to delegate work** to specialized agents. `firstmate <verb>` dispatches into the harness's `bin/fm-<verb>.sh` toolbelt. Role: `orchestrator`.
6. **Use treehouse for isolated worktrees** for agent tasks. `agent-fleet --backend treehouse` leases N pre-warmed worktrees from the pool. Role: `isolation-manager`.
7. **Run project tests / checks** with the project's own runner (`agent-test`) or `firstmate test` if a `firstmate.toml` is present. Role: `model-runtime` (the runner) + `orchestrator` (the test driver, if firstmate).
8. **Run no-mistakes as the final validation gate** with `no-mistakes doctor` and `no-mistakes status`. `agent-check` wraps both. Role: `validation-gate`.
9. **Produce a concise final report** — preferably with lavish-axi if visual review is useful. Role: `visual-collaboration` (optional) + `orchestrator` (the prose).

## What this is NOT

- Not a one-size-fits-all ordering. Steps 4 and 9 are optional (visual
  collaboration is a recommendation, not a requirement). Step 5–6 are
  skipped entirely for single-agent / single-shot sessions. Step 7 is
  just "run the tests"; there is nothing magical about it.
- Not a guarantee that every tool is installed. The default install
  (`DEFAULT_BOOTSTRAP_SET = ("herdr", "firstmate", "no-mistakes")`)
  covers the hot path. `treehouse`, `lavish-axi`, `gnhf`, and
  `wezterm` are opt-in via `--bootstrap=<name>` (or `--bootstrap=all`).
- Not a toolchain pipeline. The workbench is an orchestrator, not a
  CI system. There is no implicit cache, no implicit daemon, no
  implicit state to clean up.

## Why this matters

The previous code and docs treated each tool as a generic CLI on the
same shelf. The new mental model:

- A tool belongs to a role. The role names its place in the workflow.
- A role is filled by one tool today and may be filled by a different
  tool tomorrow. The role does not change.
- The 9-step workflow is the loop the docs and CLI surface. Tools
  are referenced by role, not by binary name, in the prose.
- Modifying dotfiles or PATH without consent is forbidden. The user
  stays in control of the persistent state of their machine.
