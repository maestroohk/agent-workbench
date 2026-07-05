# agent-workbench: run the project's test suite if one is detected.
[CmdletBinding()]
param(
    [string]$Repo,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolkitRoot = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
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

$forward = @('test')
if ($Repo) { $forward += @('--repo', $Repo) }
if ($DryRun) { $forward += '--dry-run' }

& $python (Join-Path $PythonDir 'dispatch.py') @forward
exit $LASTEXITCODE
