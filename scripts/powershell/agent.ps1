# agent-workbench: agent — unified dispatcher (verb as the first arg).
#
# Thin pass-through — all user args land in $Rest and are forwarded
# verbatim to `dispatch.py $Verb @Rest`. The inner module's main() is
# the single source of truth for argument parsing. This shim exists so
# callers can write `agent <verb> ...` instead of `agent-<verb> ...`.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('init', 'scan', 'check', 'review', 'test', 'claude', 'bootstrap', 'fleet', 'go', 'overnight')]
    [string]$Verb,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolkitRoot = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
$PythonDir = Join-Path $ToolkitRoot 'scripts\python'
$env:AGENT_WORKBENCH_HOME = $ToolkitRoot
$env:PYTHONPATH = "$PythonDir;$env:PYTHONPATH"

$python = $null
foreach ($candidate in @('python3', 'python', 'py')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $python = $found.Source
        break
    }
}

if (-not $python) {
    Write-Error "python is required to run agent-workbench"
    exit 127
}

& $python (Join-Path $PythonDir 'dispatch.py') $Verb @Rest
exit $LASTEXITCODE
