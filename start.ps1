[CmdletBinding()]
param(
    [switch]$Build,
    [int]$Port = 0,
    [switch]$Foreground
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$global:LASTEXITCODE = $null

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\runtime.ps1")

$runtimeDir = Join-Path $repoRoot ".runtime"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$docker = Get-TfvDockerCommand
$runtime = Get-TfvRuntime -RepoRoot $repoRoot -EnsureSettings
if ($Port -gt 0) {
    $runtime.ApiPort = $Port
}
$env:TIMELINE_FOR_VIDEO_API_PORT = [string]$runtime.ApiPort
$composeArgs = Get-TfvComposeArgs -RepoRoot $repoRoot -EnsureSettings
$computeMode = Get-TfvComputeMode -RepoRoot $repoRoot

Write-Host "Compute mode: $computeMode"
Write-Host "Instance name: $($runtime.InstanceName)"
Write-Host "Compose project: $($runtime.ComposeProject)"
Write-Host "API URL: http://127.0.0.1:$($runtime.ApiPort)/health"
Write-Host "Starting TimelineForVideo worker..."
$global:LASTEXITCODE = $null
$upArgs = @("up", "-d", "--remove-orphans")
if ($Build) {
    $upArgs += "--build"
}
& $docker @composeArgs @upArgs worker
if ((Get-TfvLastExitCode) -ne 0) {
    exit (Get-TfvLastExitCode)
}

Write-Host ""
Write-Host "TimelineForVideo worker API is running in the worker container."
Write-Host "Processing does not start automatically. Call the local API when processing is needed."
Write-Host ""
Write-Host "API examples:"
Write-Host "  curl.exe http://127.0.0.1:$($runtime.ApiPort)/health"
Write-Host "  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:$($runtime.ApiPort)/settings/status -Body '{}'"
Write-Host "  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:$($runtime.ApiPort)/items/refresh -Body '{""maxItems"":1}'"
Write-Host ""

if ($Foreground) {
    Write-Host "Foreground mode follows worker logs. Press Ctrl+C to stop following logs."
    $global:LASTEXITCODE = $null
    & $docker @composeArgs logs -f worker
    exit (Get-TfvLastExitCode)
}

$global:LASTEXITCODE = $null
& $docker @composeArgs ps
exit (Get-TfvLastExitCode)
