# agent-workbench: launch the model with the assembled system prompt.
[CmdletBinding()]
param(
    [string]$Repo,
    [ValidateSet('code', 'review', 'architecture', 'documentation', 'general')]
    [string]$Task = 'general',
    [string]$Model,
    [switch]$ShowPrompt,
    [switch]$PrintLoaded,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
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

$forward = @('claude', '--task', $Task)
if ($Repo) { $forward += @('--repo', $Repo) }
if ($Model) { $forward += @('--model', $Model) }
if ($ShowPrompt) { $forward += '--show-prompt' }
if ($PrintLoaded) { $forward += '--print-loaded' }
if ($Rest) { $forward += $Rest }

& $python (Join-Path $PythonDir 'dispatch.py') @forward
exit $LASTEXITCODE
