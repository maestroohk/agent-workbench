# agent-workbench: agent-go — the one-liner cold-machine bootstrap.
[CmdletBinding()]
param(
    [string]$Repo,
    [string]$Task = "general",
    [string]$Model,
    [string]$Bootstrap,
    [switch]$NoBootstrap,
    [switch]$NoCurl,
    [switch]$NoHerdr,
    [switch]$Yes,
    [switch]$PrintCmd,
    [switch]$PrintPrompt,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
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

$python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source; break }
}
if (-not $python) { Write-Error "python is required"; exit 127 }

$forward = @('go')
if ($Repo)         { $forward += @('--repo', $Repo) }
if ($Task)         { $forward += @('--task', $Task) }
if ($Model)        { $forward += @('--model', $Model) }
if ($Bootstrap)    { $forward += @('--bootstrap', $Bootstrap) }
if ($NoBootstrap)  { $forward += '--no-bootstrap' }
if ($NoCurl)       { $forward += '--no-curl' }
if ($NoHerdr)      { $forward += '--no-herdr' }
if ($Yes)          { $forward += '--yes' }
if ($PrintCmd)     { $forward += '--print-cmd' }
if ($PrintPrompt)  { $forward += '--print-prompt' }
if ($Rest)         { $forward += $Rest }

& $python (Join-Path $PythonDir 'dispatch.py') @forward
exit $LASTEXITCODE
