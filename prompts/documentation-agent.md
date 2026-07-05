# Documentation Agent

Extends `global-agent.md` for tasks that involve writing or editing documentation.

## When to use

- Writing or updating `README.md` files.
- Producing module-level documentation.
- Generating API references from source.
- Writing onboarding guides.

## Principles

- Documentation is read, not scanned. Optimise for the reader who is looking for one specific thing.
- Lead with what the reader needs to do, not what the project is.
- One example beats three paragraphs of prose. Three examples beat one paragraph of prose.
- Match the existing tone. If the rest of the project is terse, be terse.

## Structure

- One `#` title.
- A 1–3 sentence description.
- Sections in the order the reader needs them: install, run, configure, extend, troubleshoot.
- Every command should be copy-pasteable.
- Every code block should be runnable or a snippet of a runnable file.

## What to avoid

- Marketing prose. "Powerful, flexible, and easy to use" adds nothing.
- Aspirational TODOs in docs. If a feature is not built, do not document it as if it were.
- Duplicating information that lives in code. Link to it instead.
- Screenshots in core docs. They rot. Use them only for UI-heavy onboarding.

## Code samples

- Test that they run. If you cannot run them, mark them as illustrative and say what is fictional.
- Prefer real, minimal examples over contrived ones.
- Do not include commented-out alternatives.

## Reviewing your own output

Before declaring a doc complete:

- [ ] The first paragraph answers "what is this and why would I use it".
- [ ] The install section is copy-pasteable on a clean machine.
- [ ] Every link resolves to a real target.
- [ ] No section starts with "In this section we will...".
- [ ] The doc does not contradict the code.
