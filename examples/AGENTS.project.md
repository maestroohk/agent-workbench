# AGENTS.project.md

Project-specific rules for AI agents. Drop this file in the repository root and the
`agent-claude` launcher will pick it up automatically.

Anything in this file overrides or extends `AGENTS.md` (the global rules). It does not
replace them — the global rules still apply.

---

## 1. Project overview

One paragraph. What is this project, who owns it, what stack is it on.

## 2. Domain rules

- List the business invariants the agent must respect.
- Mention any tables, columns, APIs, or configuration keys that are off-limits without
  human approval.

## 3. Conventions specific to this repo

- Naming patterns, file layout, internal libraries.
- Things that look unusual but are intentional.

## 4. Non-goals

- What the agent must not do in this project. Be specific.

## 5. Test data

- Where the test database lives, how to seed it, how to reset it.
- Any test fixtures that look real but are not.

## 6. Owners and contact

- Who to ping for changes in each area. The agent will not message them, but
  the prompt assembler will surface this when the user asks "who owns X".
