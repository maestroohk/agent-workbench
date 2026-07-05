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
#   3. Adds $env:USERPROFILE\.local\bin to PATH for the current and
#      future sessions (HKCU registry; no admin required).
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

# 3. Add ~/.local/bin to PATH for the current session and future sessions.
$currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($currentPath -notlike "*${BinDir}*") {
    [Environment]::SetEnvironmentVariable('Path', "${BinDir};${currentPath}", 'User')
    Say "added $BinDir to your user PATH (restart shells to pick up)"
}
$env:Path = "${BinDir};$env:Path"

# 4. Next step.
Say ""
Say "all set. Try it on any repo:"
Say "    cd C:\path\to\your\repo"
Say "    agent-go"
