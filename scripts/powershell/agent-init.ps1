# agent-workbench: install or update the toolkit.
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$PrintPlatform
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

$forward = @('init')
if ($Force) { $forward += '--force' }
if ($PrintPlatform) { $forward += '--print-platform' }

& $python (Join-Path $PythonDir 'dispatch.py') @forward
exit $LASTEXITCODE
