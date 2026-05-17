[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$global:LASTEXITCODE = $null

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\runtime.ps1")

$apiPidFile = Join-Path $repoRoot ".runtime\api.pid"

function Stop-TfvNativeApi {
    if (-not (Test-Path -LiteralPath $apiPidFile)) {
        return
    }

    $pidText = (Get-Content -LiteralPath $apiPidFile -Raw).Trim()
    $pidValue = 0
    if ([int]::TryParse($pidText, [ref]$pidValue)) {
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        }
    }

    Remove-Item -LiteralPath $apiPidFile -Force -ErrorAction SilentlyContinue
}

Stop-TfvNativeApi

$docker = Get-TfvDockerCommand
$runtime = Get-TfvRuntime -RepoRoot $repoRoot -LegacyIfMissing
$composeArgs = Get-TfvComposeArgs -RepoRoot $repoRoot -LegacyIfMissing

Write-Host "Stopping TimelineForVideo worker and API..."
Write-Host "Compose project: $($runtime.ComposeProject)"
$global:LASTEXITCODE = $null
& $docker @composeArgs down --remove-orphans
exit (Get-TfvLastExitCode)
