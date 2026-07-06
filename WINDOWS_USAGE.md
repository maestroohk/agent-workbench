# Windows quickstart

> The flow that takes you from a clean Windows box to a working agent
> session in a herdr pane. If anything here does not match what you
> see on screen, file a bug — the previous round had three silent
> failures (WinError 193, `--tab new` placement, gnhf install noise)
> that this doc and the code behind it now prevent.

## 0. One-time install

```powershell
iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1)
```

The installer:

- Clones the workbench into `~/.agent-workbench/`.
- Drops PowerShell and bash shims into `~/.local/bin/` (e.g.
  `agent-go.ps1`, `agent-scan`, `agent-check`).
- Asks before persisting `~/.local/bin` to your user PATH (the
  session-only `PATH` is always set so the rest of the install works
  either way).
- Installs the bootstrap toolchain: `claude`, `herdr`, `firstmate`,
  `no-mistakes`, `ollama` (the slim default set; gnhf and treehouse
  are opt-in).

Verify:

```powershell
agent-go --print-cmd
```

That should print the install one-liner above and exit 0.

## 1. Open the repo

```powershell
cd C:\path\to\your\repo
```

`agent-workbench` auto-detects the repo root by walking up looking
for `.git`, `AGENTS.project.md`, `CLAUDE.md`, or any of the standard
manifest files (`package.json`, `pyproject.toml`, etc.). You should
not need to pass `--repo`.

## 2. Generate the system prompt inputs

```powershell
agent-scan
```

Creates `.agent/` with stack-detection summaries. One-time per repo
(or whenever the stack changes).

## 3. Sanity-check the repo

```powershell
agent-check
```

Runs `firstmate doctor` (project structure), `no-mistakes doctor`
(toolchain health), and the standard preflight. One line per check.
If anything is `[err]`, fix that first.

## 4. The documented flow: `agent-go --task code`

```powershell
agent-go --task code
```

What happens, in order:

1. Bootstrap probes. If a default tool is missing, it installs the
   slim set (`claude, herdr, firstmate, no-mistakes, ollama`).
2. The system prompt is assembled from `AGENTS.md`, the coding-agent
   task prompt, any detected profiles, and your repo's
   `AGENTS.project.md` / `CLAUDE.md` / `docs/agent-rules/*.md`.
3. The prompt is written to `.agent/SYSTEM_PROMPT.md` (Claude Code
   auto-loads it).
4. The herdr server is started in the background (if not already
   running).
5. A herdr agent is spawned in a right-split pane running
   `claude.cmd` with the system prompt appended.
6. The shell prints one line telling you how to attach:
   `agent started in herdr pane primary (terminal: <id>). Use
   \`herdr agent attach primary\` to follow, or paste your task
   prompt in the pane.`

At this point you are back at the PowerShell prompt. Open the herdr
pane (or `herdr agent attach primary`) and paste the task prompt
that was printed by `agent-go`.

### What if the herdr pane does not open?

The flow above is the happy path. Two of the things that can go
wrong and how to recover:

**A. `herdr worktree create` failed on a fresh repo (no commits).**
You will see:

```
agent-workbench: herdr worktree create failed (fatal: invalid
reference: HEAD); running agent in repo root instead
agent-workbench: starting herdr agent 'primary' in <repo>
(use 'herdr agent attach primary' to follow)
```

This is the new fallback: the agent is spawned in the repo root
instead of a fresh worktree, and you still get the herdr pane. If
you want a clean worktree, commit your changes first
(`git add -A && git commit -m "wip"`) and re-run.

**B. `herdr agent start` failed for some other reason (server
wedged, agent name taken, etc.).** You will see:

```
agent-workbench: herdr agent start failed (exit 1); falling back
to direct claude
```

The fallback path runs `claude.cmd` directly in the current
PowerShell, with the same system prompt. This is the `--no-herdr`
path, but you do not need to re-run — the shim already fell back
for you.

If the fallback also fails, run the read-only path (section 5) to
verify the prompt is intact, then file a bug.

## 5. The read-only path: `agent-go --print-prompt`

If you want the assembled system prompt without launching anything,
or you want to capture it to a file for offline use:

```powershell
agent-go --print-prompt
```

This:

- Does NOT touch the network. No install step.
- Does NOT start the herdr server.
- Does NOT launch the model.
- Writes the assembled prompt to stdout (UTF-8, ~27 KB on a typical
  repo) and exits 0.

To save to a file:

```powershell
agent-go --print-prompt | Out-File -Encoding utf8 .\my-prompt.md
```

You can then paste the prompt into a manual `claude` session, hand
it to a colleague, or diff it against a previous run.

## 6. The skip-herdr path: `agent-go --task code --no-herdr`

If you do not want the herdr pane at all (e.g. you are on a
machine without a graphical terminal, or you want the agent to run
inline in your current PowerShell):

```powershell
agent-go --task code --no-herdr
```

This skips the herdr server startup and spawns `claude.cmd` directly
in the current PowerShell. The system prompt is the same. The user
experience is "I am now talking to claude in this terminal" — the
opposite of the herdr-pane flow.

## 7. Troubleshooting

### "I got dropped back at the PowerShell prompt with no clear error."

You ran `agent-go` and the shell came back immediately. Read the
last 5–10 lines of `agent-workbench:` info messages. One of them
will be the cause. The common cases are:

- `herdr worktree create failed (...)` — see (A) above.
- `herdr agent start failed (exit N); falling back to direct claude`
  — the shim already fell back; if the fallback did not work, run
  `agent-go --task code --no-herdr` to force the inline path.
- `claude CLI not found; falling back to ollama run` — `claude` is
  not on PATH. Run `agent-init --bootstrap=claude` or check that
  `~/.local/bin` (or `%APPDATA%\npm`) is on PATH.

### "I got an `OSError: [WinError 193] %1 is not a valid Win32 application`."

This was the bug fixed in this round. The bare `claude` on PATH is
a Node.js shim, not a PE binary, and `subprocess.run` calling
`CreateProcessW` directly on it used to blow up. The fix is in
`utils.resolve_executable()`: on Windows it prefers `claude.cmd`
over the bare shim. If you are still seeing this:

- Confirm `claude.cmd` is on PATH:
  ```powershell
  Get-Command claude.cmd
  ```
  If that returns nothing, `claude` was not installed by the npm
  installer as a `.cmd` entry point. Reinstall:
  ```powershell
  npm install -g @anthropic-ai/claude-code
  ```
- Confirm the workbench is on the latest commit (the fix is in
  `scripts/python/utils.py`).

### "Bootstrap printed 'no asset matching gnhf' and stopped."

`gnhf` is the overnight runner and ships no Windows release. It
was removed from `DEFAULT_GO_BOOTSTRAP` in this round, so a normal
`agent-go` should not hit it. If you see this, your checkout is
out of date — pull the latest main. If you actually want gnhf on
Windows, install it manually: see
[tools/gnhf.md](tools/gnhf.md) for the (currently empty) install
path.

### "herdr says `agent placement target new not found`."

The shim used to call `herdr agent start <name> --tab new`, which
herdr rejected (`--tab` expects an existing tab ID, not the literal
`new`). The fix is `--split right --no-focus`. If you are still
seeing this, your checkout is out of date.

## 8. gnhf on Windows

`gnhf` is the overnight runner. As of 2026-07-06 it has no
Windows release. To use it on Windows you would need to:

1. Clone `github.com/kunchenguid/gnhf` and build from source.
2. Place the binary on PATH (e.g. `~/.local/bin/gnhf.exe`).
3. Run `agent-overnight` (or `agent-go --bootstrap=gnhf` if you
   need the auto-install path; the install will be a no-op).

The default `agent-go` flow does not use gnhf; only `agent-overnight`
does. The default bootstrap does not pull gnhf on any platform, so
a clean Windows install does not see the "no asset" error.

## 9. Other tools in the workbench

- `agent-fleet N` — spawns N claude agents in parallel on isolated
  worktrees. Use this for parallel research / refactor / review
  work. Backend: herdr (default) or treehouse (opt-in
  `--bootstrap=treehouse`).
- `agent-test` — runs the project's test suite (delegates to
  `firstmate test` if a `firstmate.toml` is in the repo root).
- `agent-review` — assembles the review prompt and prints it (the
  same as `agent-go --task review --print-prompt`).
- `agent-bootstrap` — installs the bootstrap toolchain on demand,
  scoped by `--bootstrap=<list>`.
- `agent-overnight` — runs gnhf with safe defaults. See
  [tools/gnhf.md](tools/gnhf.md).

See [README.md](README.md) for the full command list and
[tools/](tools/) for per-tool documentation.
