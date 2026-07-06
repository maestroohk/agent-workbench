# agent-workbench one-line installer for Windows PowerShell.
#
# Paste this in any PowerShell on a clean machine:
#
#   iex (irm https://raw.githubusercontent.com/maestroohk/agent-workbench/main/install.ps1)
#
# What it does:
#   1. Clones https://github.com/maestroohk/agent-workbench into
#      $env:USERPROFILE\.agent-workbench (or uses an existing checkout).
#   2. Runs agent-init which:
#        - symlinks (or copies) the eight helper shims into
#          $env:USERPROFILE\.local\bin
#        - bootstraps claude, herdr, firstmate, no-mistakes, treehouse,
#          gnhf, ollama, wezterm via winget / choco / curl-piped installer
#        - writes the agent-workbench-home marker file so the shims
#          resolve back to the toolkit root from .local\bin
#   3. Asks before persisting $BinDir to the user PATH (HKCU); applies
#      a session-only PATH change regardless so the rest of the
#      installer and any tools run in the same session can resolve
#      the shims.
#   4. Prints the next step: `cd <your repo>; agent-go`
#
$ErrorActionPreference = 'Stop'

$RepoUrl = 'https://github.com/maestroohk/agent-workbench.git'
$InstallRoot = Join-Path $env:USERPROFILE '.agent-workbench'
$BinDir = Join-Path $env:USERPROFILE '.local\bin'

function Say($msg) { Write-Host "[agent-workbench] $msg" -ForegroundColor Cyan }

Say "install root: $InstallRoot"
Say "shim dir:     $BinDir"

# 1. Clone (or update) the toolkit.
if (-not (Test-Path (Join-Path $InstallRoot 'scripts\python\dispatch.py'))) {
    if (Test-Path $InstallRoot) {
        Say "removing stale $InstallRoot (no dispatch.py found)"
        Remove-Item -Recurse -Force $InstallRoot
    }
    Say "cloning $RepoUrl"
    git clone $RepoUrl $InstallRoot
} else {
    Say "existing checkout found; pulling latest"
    Push-Location $InstallRoot
    try { git pull --ff-only } catch { Say "pull failed (offline?); continuing with the existing checkout" }
    Pop-Location
}

# 2. Run agent-init which symlinks the shims + bootstraps tools.
$python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source; break }
}
if (-not $python) {
    Say "python is required (install from https://python.org/downloads/)"
    exit 127
}
$env:AGENT_WORKBENCH_HOME = $InstallRoot
$env:PYTHONPATH = (Join-Path $InstallRoot 'scripts\python')
& $python (Join-Path $InstallRoot 'scripts\python\dispatch.py') init --bootstrap=all

# 3. Add ~/.local/bin to PATH for the current session and (with the
#    user's explicit consent) future sessions. The HKCU user-scope
#    registry write is gated by a y/N prompt; the session-only change
#    below is applied regardless.
$currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($currentPath -notlike "*${BinDir}*") {
    $proposed = "${BinDir};${currentPath}"
    Say ""
    Say "to make the shims available in future PowerShell sessions, persist this"
    Say "to your user PATH (HKCU; no admin required):"
    Say ""
    Say "    $proposed"
    Say ""
    $answer = Read-Host -Prompt "Apply this change? [y/N]"
    if ($answer -match '^[Yy]') {
        [Environment]::SetEnvironmentVariable('Path', $proposed, 'User')
        Say "added $BinDir to your user PATH (restart shells to pick up)"
    } else {
        Say "skipped: add $BinDir to your user PATH manually if you want it persistent"
    }
}
$env:Path = "${BinDir};$env:Path"

# 4. Next step.
Say ""
Say "all set. Try it on any repo:"
Say "    cd C:\path\to\your\repo"
Say "    agent-go"
