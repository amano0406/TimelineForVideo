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
$apiPidFile = Join-Path $runtimeDir "api.pid"
$apiProject = Join-Path $repoRoot "api\TimelineForVideo.HealthApi\TimelineForVideo.HealthApi.csproj"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

function Test-TfvApiCommandLine {
    param([string]$CommandLine)

    if (-not $CommandLine) {
        return $false
    }

    $escapedRepoRoot = [regex]::Escape($repoRoot)
    return (
        ($CommandLine -match "TimelineForVideo\.HealthApi(\.csproj|\.dll|\.exe)?") -and
        ($CommandLine -match $escapedRepoRoot)
    )
}

function Get-TfvApiProcess {
    try {
        $matches = @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object { Test-TfvApiCommandLine -CommandLine ([string]$_.CommandLine) }
        )
    }
    catch {
        return $null
    }

    if ($matches.Count -eq 0) {
        return $null
    }

    $projectHost = @($matches | Where-Object { [string]$_.CommandLine -match "TimelineForVideo\.HealthApi\.csproj" } | Select-Object -First 1)
    if ($projectHost.Count -gt 0) {
        return $projectHost[0]
    }

    return ($matches | Select-Object -First 1)
}

function Start-TfvNativeApi {
    param(
        [int]$ApiPort,
        [switch]$RunInForeground
    )

    if (-not (Test-Path -LiteralPath $apiProject -PathType Leaf)) {
        throw "TimelineForVideo API project was not found: $apiProject"
    }

    if (Test-Path -LiteralPath $apiPidFile) {
        $existingPidText = (Get-Content -LiteralPath $apiPidFile -Raw).Trim()
        $existingPid = 0
        if ([int]::TryParse($existingPidText, [ref]$existingPid)) {
            $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
            if ($null -ne $existing) {
                $commandLine = ""
                try {
                    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $existingPid"
                    if ($null -ne $cim) {
                        $commandLine = [string]$cim.CommandLine
                    }
                }
                catch {
                    $commandLine = ""
                }
                if (Test-TfvApiCommandLine -CommandLine $commandLine) {
                    Write-Host "TimelineForVideo API is already running. pid=$existingPid"
                    return
                }
            }
        }
        Remove-Item -LiteralPath $apiPidFile -Force
    }

    $running = Get-TfvApiProcess
    if ($null -ne $running) {
        Set-Content -LiteralPath $apiPidFile -Value ([string]$running.ProcessId) -Encoding ASCII
        Write-Host "TimelineForVideo API is already running. pid=$($running.ProcessId)"
        return
    }

    $apiArgs = @(
        "run",
        "--project",
        $apiProject,
        "--no-launch-profile",
        "--",
        "--product-root",
        $repoRoot,
        "--port",
        [string]$ApiPort
    )

    if ($RunInForeground) {
        & dotnet @apiArgs
        exit $LASTEXITCODE
    }

    $process = Start-Process -FilePath "dotnet" -ArgumentList $apiArgs -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $apiPidFile -Value ([string]$process.Id) -Encoding ASCII
    Write-Host "TimelineForVideo API started. pid=$($process.Id)"
}

$docker = Get-TfvDockerCommand
$runtime = Get-TfvRuntime -RepoRoot $repoRoot -EnsureSettings
if ($Port -gt 0) {
    $runtime.ApiPort = $Port
    $env:TIMELINE_FOR_VIDEO_API_PORT = [string]$Port
}
$composeArgs = Get-TfvComposeArgs -RepoRoot $repoRoot -EnsureSettings
$computeMode = Get-TfvComputeMode -RepoRoot $repoRoot

Write-Host "Compute mode: $computeMode"
Write-Host "Instance name: $($runtime.InstanceName)"
Write-Host "Compose project: $($runtime.ComposeProject)"
Write-Host "API URL: http://127.0.0.1:$($runtime.ApiPort)/health"
Write-Host "Starting TimelineForVideo command worker..."
$global:LASTEXITCODE = $null
$upArgs = @("up", "-d", "--remove-orphans")
if ($Build) {
    $upArgs += "--build"
}
& $docker @composeArgs @upArgs worker
if ((Get-TfvLastExitCode) -ne 0) {
    exit (Get-TfvLastExitCode)
}

Start-TfvNativeApi -ApiPort ([int]$runtime.ApiPort) -RunInForeground:$Foreground

Write-Host ""
Write-Host "TimelineForVideo command worker and API are running."
Write-Host "Processing does not start automatically. Call the local API when processing is needed."
Write-Host ""
Write-Host "API examples:"
Write-Host "  curl.exe http://127.0.0.1:$($runtime.ApiPort)/health"
Write-Host "  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:$($runtime.ApiPort)/settings/status -Body '{}'"
Write-Host "  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:$($runtime.ApiPort)/items/refresh -Body '{""maxItems"":1}'"
Write-Host ""

$global:LASTEXITCODE = $null
& $docker @composeArgs ps
exit (Get-TfvLastExitCode)
