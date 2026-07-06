# agent-workbench: validate the current repository.
#
# Thin pass-through — see agent-go.ps1 for the rationale. All user args
# land in $Rest and are forwarded verbatim to `dispatch.py check`. The
# inner `agent_check.main()` is the single source of truth for argument
# parsing.
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# Resolve the toolkit root. Order:
#  1. AGENT_WORKBENCH_HOME env var (set by `agent-init` and by the bash dispatcher).
#  2. The marker file `agent-workbench-home` written by `agent-init` next to the
#     installed shims (so PowerShell wrappers can find the toolkit from
#     ~/.local/bin/ without walking the wrong tree).
#  3. Walk up from $ScriptDir looking for `scripts\python\dispatch.py`.
#  4. Fall back to $ScriptDir\..\.. for the in-tree case.
$ToolkitRoot = $env:AGENT_WORKBENCH_HOME
if (-not $ToolkitRoot -or -not (Test-Path (Join-Path $ToolkitRoot 'scripts\python\dispatch.py'))) {
    $marker = Join-Path $ScriptDir 'agent-workbench-home'
    if (Test-Path $marker) {
        $candidate_root = (Get-Content $marker -Raw).Trim()
        if ($candidate_root -and (Test-Path (Join-Path $candidate_root 'scripts\python\dispatch.py'))) {
            $ToolkitRoot = $candidate_root
        }
    }
}
if (-not $ToolkitRoot) {
    $candidate = $ScriptDir
    for ($i = 0; $i -lt 6; $i++) {
        if (Test-Path (Join-Path $candidate 'scripts\python\dispatch.py')) {
            $ToolkitRoot = (Resolve-Path $candidate).Path
            break
        }
        $parent = Split-Path -Parent $candidate
        if (-not $parent -or $parent -eq $candidate) { break }
        $candidate = $parent
    }
}
if (-not $ToolkitRoot) { $ToolkitRoot = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path }
$PythonDir = Join-Path $ToolkitRoot 'scripts\python'
$env:AGENT_WORKBENCH_HOME = $ToolkitRoot
$env:PYTHONPATH = "$PythonDir;$env:PYTHONPATH"

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) {
    Write-Error "python is required to run agent-workbench"
    exit 127
}

& $python (Join-Path $PythonDir 'dispatch.py') 'check' @Rest
exit $LASTEXITCODE
