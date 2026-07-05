# agent-workbench dispatcher (PowerShell).
# All business logic lives in scripts/python/. This wrapper only sets up the
# environment and invokes Python.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('init', 'scan', 'check', 'review', 'test', 'claude')]
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

$argsList = @($Verb) + $Rest
& $python (Join-Path $PythonDir 'dispatch.py') @argsList
exit $LASTEXITCODE
