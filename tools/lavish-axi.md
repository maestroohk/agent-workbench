# lavish-axi

A local-first HTML authoring tool designed for human + AI collaboration
on HTML artifacts. "HTML is the new markdown; lavish is the new editor
for your HTML artifacts." Written by the same author as `firstmate`,
`no-mistakes`, and `treehouse`.

## Purpose

- Agents write the HTML artifact; humans annotate elements, text
  ranges, or Mermaid nodes locally and send feedback back.
- The artifact is the source of truth; the comment trail is the
  review log.
- Local-first, cross-platform (macOS, Linux, Windows), MIT-licensed.

## Where it provides value in an AI workflow

- An agent generates an HTML mockup, design doc, or schema diagram.
- The human annotates specific elements and the agent reads the
  annotations to revise.
- Especially useful for Mermaid diagrams and inline screenshots where
  conversational feedback is awkward.

## Installation

The primary install is via the `npx skills add` flow (no separate
`npm install` required):

```bash
npx skills add kunchenguid/lavish-axi --skill lavish
```

Add `-g` to install globally. The skill teaches the agent to invoke
lavish on demand via `npx -y lavish-axi`.

Alternative: `npm install -g lavish-axi && lavish-axi setup hooks` to
register the setup hook path with Claude Code, Codex, OpenCode, and
GitHub Copilot CLI.

## Recommended usage

- Ask the agent to produce an HTML artifact (a diagram, a design doc,
  a screenshot mockup).
- The agent runs `lavish-axi annotate <file>` to open a local
  annotation UI.
- You click on elements, leave comments, save.
- The agent reads the annotations and revises.

## Best practices

- Use lavish for artifacts you will iterate on (design docs, mockups,
  diagram families). For one-off HTML, plain markdown is fine.
- Keep the artifacts in version control; lavish stores annotations
  alongside the HTML.

## Integration with `agent-workbench`

- `agent-init --bootstrap=lavish-axi` runs the `npx skills add` step.
- The workbench does not auto-invoke lavish-axi; the agent itself
  decides when annotation is appropriate.

## Limitations

- Adds a Node.js + browser dependency.
- Annotations are local-first; sharing them requires the file to be
  committed.
- The skill model assumes the agent harness supports the
  `npx skills add` flow (Claude Code, Codex, OpenCode, Copilot CLI
  do).

## References

- Source: <https://github.com/kunchenguid/lavish-axi> (MIT, 1.6k stars)
- Latest: `v0.1.36` (Jul 2026)
- Companion tools: `firstmate`, `no-mistakes`, `treehouse`, `gnhf`
