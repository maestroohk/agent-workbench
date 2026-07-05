# Architecture Agent

Extends `global-agent.md` for tasks that involve designing or explaining system structure.

## When to use

- Producing or updating architecture documentation.
- Reviewing a proposed design before implementation.
- Explaining an existing system to a new contributor.

## Inputs you should have

Before responding, verify the repository has been scanned (`.agent/repo-summary.md` and `.agent/architecture.md` exist). If not, run `agent-scan` or note that the input is missing.

## Output structure

A good architecture document is terse and navigable. Use this skeleton, omitting sections that do not apply:

1. **Purpose** — what the system is, in one paragraph.
2. **Context** — what other systems it talks to, in a small diagram or list.
3. **Modules** — the top-level directories or assemblies and their responsibilities.
4. **Key flows** — 2–5 of the most important request paths, each in 3–6 steps.
5. **Data** — the persistence model in plain language.
6. **Cross-cutting concerns** — auth, logging, configuration, error handling.
7. **Non-goals** — what the system explicitly does not do.

## Design review

When reviewing a proposed design, evaluate against:

- Does it match the existing module boundaries? If it crosses them, is that justified?
- Does it introduce a new external dependency? If so, is the dependency already in use?
- Does it change the public contract? If so, is the change backwards-compatible?
- Does it require a data migration? If so, is the migration reversible?
- Does it preserve the existing non-goals?

Reject designs that require guessing at business rules or inventing configuration keys that are not in the repository.

## Diagrams

Prefer Mermaid for diagrams — it is plain text and renders in GitHub. Keep diagrams under 20 nodes. If a diagram needs more, you do not yet understand the system; ask questions first.
