Set-StrictMode -Version Latest

$script:TfvProductSlug = "timeline-for-video"
$script:TfvDefaultApiPort = 19500

function Get-TfvSettingsPath {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    return (Join-Path $RepoRoot "settings.json")
}

function Get-TfvSettingsExamplePath {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    return (Join-Path $RepoRoot "settings.example.json")
}

function Get-TfvDockerCommand {
    $dockerExe = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $dockerExe) { return $dockerExe }

    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }

    throw "docker.exe was not found. Install or start Docker Desktop."
}

function Get-TfvLastExitCode {
    if ($null -eq $global:LASTEXITCODE) {
        return 1
    }

    return [int]$global:LASTEXITCODE
}

function Get-TfvJsonProperty {
    param(
        [object]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [object]$Default = $null
    )

    if ($null -eq $Object) {
        return $Default
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $Default
    }

    return $property.Value
}

function Set-TfvJsonProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [object]$Value
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        Add-Member -InputObject $Object -MemberType NoteProperty -Name $Name -Value $Value
        return
    }

    $property.Value = $Value
}

function Normalize-TfvSlug {
    param([string]$Value)

    $text = ([string]$Value).Trim().ToLowerInvariant()
    $text = [System.Text.RegularExpressions.Regex]::Replace($text, "[^a-z0-9-]+", "-")
    $text = [System.Text.RegularExpressions.Regex]::Replace($text, "-+", "-").Trim("-")
    return $text
}

function Normalize-TfvInstanceName {
    param([string]$Value)

    $text = Normalize-TfvSlug -Value $Value
    if ($text.StartsWith("local-")) {
        return $text.Substring(6)
    }
    return $text
}

function New-TfvInstanceName {
    return ([guid]::NewGuid().ToString("N").Substring(0, 10)).ToLowerInvariant()
}

function ConvertTo-TfvPort {
    param(
        [object]$Value,
        [int]$Default = $script:TfvDefaultApiPort
    )

    if ($null -eq $Value) {
        return $Default
    }

    $text = ([string]$Value).Trim()
    if (-not $text) {
        return $Default
    }

    $port = 0
    if (-not [int]::TryParse($text, [ref]$port)) {
        throw "runtime.apiPort must be an integer."
    }
    if ($port -lt 1 -or $port -gt 65535) {
        throw "runtime.apiPort must be between 1 and 65535."
    }
    return $port
}

function Read-TfvSettingsObject {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$CreateIfMissing
    )

    $settingsPath = Get-TfvSettingsPath -RepoRoot $RepoRoot
    if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
        return (Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json)
    }

    if (-not $CreateIfMissing) {
        return $null
    }

    $examplePath = Get-TfvSettingsExamplePath -RepoRoot $RepoRoot
    if (Test-Path -LiteralPath $examplePath -PathType Leaf) {
        return (Get-Content -LiteralPath $examplePath -Raw | ConvertFrom-Json)
    }

    return [pscustomobject]@{
        schemaVersion = 1
        inputRoots = @("C:\TimelineData\input-video\")
        outputRoot = "C:\TimelineData\video"
        huggingfaceToken = ""
        computeMode = "gpu"
    }
}

function Save-TfvSettingsObject {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][object]$Settings
    )

    $settingsPath = Get-TfvSettingsPath -RepoRoot $RepoRoot
    $json = (ConvertTo-TfvOrderedSettings -Settings $Settings) | ConvertTo-Json -Depth 32
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($settingsPath, ($json + [Environment]::NewLine), $utf8NoBom)
}

function ConvertTo-TfvOrderedSettings {
    param([Parameter(Mandatory = $true)][object]$Settings)

    $runtime = Get-TfvJsonProperty -Object $Settings -Name "runtime" -Default $null
    $ordered = [ordered]@{
        schemaVersion = Get-TfvJsonProperty -Object $Settings -Name "schemaVersion" -Default 1
    }
    if ($null -ne $runtime) {
        $ordered.runtime = [ordered]@{
            instanceName = Get-TfvJsonProperty -Object $runtime -Name "instanceName" -Default ""
            apiPort = ConvertTo-TfvPort -Value (Get-TfvJsonProperty -Object $runtime -Name "apiPort" -Default $script:TfvDefaultApiPort)
        }
    }
    $ordered.inputRoots = @(Get-TfvJsonProperty -Object $Settings -Name "inputRoots" -Default @())
    $ordered.outputRoot = Get-TfvJsonProperty -Object $Settings -Name "outputRoot" -Default "C:\TimelineData\video"
    $ordered.huggingfaceToken = Get-TfvJsonProperty `
        -Object $Settings `
        -Name "huggingfaceToken" `
        -Default (Get-TfvJsonProperty -Object $Settings -Name "huggingFaceToken" -Default "")
    $ordered.computeMode = Get-TfvJsonProperty -Object $Settings -Name "computeMode" -Default "gpu"
    return [pscustomobject]$ordered
}

function Get-TfvRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$EnsureSettings,
        [switch]$LegacyIfMissing
    )

    $settings = Read-TfvSettingsObject -RepoRoot $RepoRoot -CreateIfMissing:$EnsureSettings
    $runtime = Get-TfvJsonProperty -Object $settings -Name "runtime" -Default $null
    $changed = $false

    if ($EnsureSettings -and $null -eq $runtime) {
        $runtime = [pscustomobject]@{}
        Set-TfvJsonProperty -Object $settings -Name "runtime" -Value $runtime
        $changed = $true
    }

    $envInstance = Normalize-TfvInstanceName -Value ([Environment]::GetEnvironmentVariable("TIMELINE_FOR_VIDEO_INSTANCE_NAME", "Process"))
    $settingsInstance = Normalize-TfvInstanceName -Value ([string](Get-TfvJsonProperty -Object $runtime -Name "instanceName" -Default ""))

    if ($envInstance) {
        $instanceName = $envInstance
        if ($EnsureSettings -and -not $settingsInstance) {
            Set-TfvJsonProperty -Object $runtime -Name "instanceName" -Value $instanceName
            $settingsInstance = $instanceName
            $changed = $true
        }
    }
    elseif ($settingsInstance) {
        $instanceName = $settingsInstance
    }
    elseif ($EnsureSettings) {
        $instanceName = New-TfvInstanceName
        Set-TfvJsonProperty -Object $runtime -Name "instanceName" -Value $instanceName
        $settingsInstance = $instanceName
        $changed = $true
    }
    elseif ($LegacyIfMissing) {
        $instanceName = "legacy"
    }
    else {
        throw "runtime.instanceName is missing. Run .\start.ps1 first."
    }

    $rawSettingsInstance = [string](Get-TfvJsonProperty -Object $runtime -Name "instanceName" -Default "")
    if ($EnsureSettings -and $settingsInstance -and $settingsInstance -ne $rawSettingsInstance) {
        Set-TfvJsonProperty -Object $runtime -Name "instanceName" -Value $settingsInstance
        $changed = $true
    }

    $envPort = [Environment]::GetEnvironmentVariable("TIMELINE_FOR_VIDEO_API_PORT", "Process")
    $settingsPortValue = Get-TfvJsonProperty -Object $runtime -Name "apiPort" -Default $null
    $apiPort = if ($envPort) { ConvertTo-TfvPort -Value $envPort } else { ConvertTo-TfvPort -Value $settingsPortValue }

    if ($EnsureSettings -and $null -eq $settingsPortValue) {
        Set-TfvJsonProperty -Object $runtime -Name "apiPort" -Value $apiPort
        $changed = $true
    }

    if ($EnsureSettings -and $changed) {
        Save-TfvSettingsObject -RepoRoot $RepoRoot -Settings $settings
    }

    $envComposeProject = Normalize-TfvSlug -Value ([Environment]::GetEnvironmentVariable("TIMELINE_FOR_VIDEO_COMPOSE_PROJECT", "Process"))
    if (-not $envComposeProject) {
        $envComposeProject = Normalize-TfvSlug -Value ([Environment]::GetEnvironmentVariable("COMPOSE_PROJECT_NAME", "Process"))
    }

    $composeProject = $envComposeProject
    if (-not $composeProject) {
        if ($LegacyIfMissing -and $instanceName -eq "legacy" -and -not $settingsInstance -and -not $envInstance) {
            $composeProject = $script:TfvProductSlug
        }
        else {
            $composeProject = "$script:TfvProductSlug-$instanceName"
        }
    }

    $imageTag = Normalize-TfvSlug -Value ([Environment]::GetEnvironmentVariable("TIMELINE_FOR_VIDEO_IMAGE_TAG", "Process"))
    if (-not $imageTag) {
        if ($LegacyIfMissing -and $instanceName -eq "legacy" -and -not $settingsInstance -and -not $envInstance) {
            $imageTag = "latest"
        }
        else {
            $imageTag = $composeProject
        }
    }

    $env:TIMELINE_FOR_VIDEO_INSTANCE_NAME = $instanceName
    $env:TIMELINE_FOR_VIDEO_COMPOSE_PROJECT = $composeProject
    $env:TIMELINE_FOR_VIDEO_IMAGE_TAG = $imageTag
    $env:TIMELINE_FOR_VIDEO_API_PORT = [string]$apiPort

    return [pscustomobject]@{
        InstanceName = $instanceName
        ComposeProject = $composeProject
        ImageTag = $imageTag
        ApiPort = $apiPort
        SettingsPath = (Get-TfvSettingsPath -RepoRoot $RepoRoot)
    }
}

function Get-TfvComputeMode {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $settingsPath = Get-TfvSettingsPath -RepoRoot $RepoRoot
    if (-not (Test-Path -LiteralPath $settingsPath)) {
        return "gpu"
    }

    try {
        $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        $mode = [string]$settings.computeMode
        if ($mode.ToLowerInvariant() -eq "cpu") {
            return "cpu"
        }
    }
    catch {
        return "gpu"
    }

    return "gpu"
}

function Set-TfvDefaultMountEnvironment {
    if (-not $env:TIMELINE_FOR_VIDEO_C_DRIVE_MOUNT) {
        $env:TIMELINE_FOR_VIDEO_C_DRIVE_MOUNT = "C:\"
    }
    if (-not $env:TIMELINE_FOR_VIDEO_F_DRIVE_MOUNT) {
        $env:TIMELINE_FOR_VIDEO_F_DRIVE_MOUNT = "F:\"
    }
}

function Get-TfvComposeArgs {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$EnsureSettings,
        [switch]$LegacyIfMissing
    )

    Set-TfvDefaultMountEnvironment
    $runtime = Get-TfvRuntime -RepoRoot $RepoRoot -EnsureSettings:$EnsureSettings -LegacyIfMissing:$LegacyIfMissing
    $args = @("compose", "--project-directory", $RepoRoot, "-p", $runtime.ComposeProject)
    if ((Get-TfvComputeMode -RepoRoot $RepoRoot) -eq "gpu") {
        $args += @("-f", (Join-Path $RepoRoot "docker-compose.yml"))
        $args += @("-f", (Join-Path $RepoRoot "docker-compose.gpu.yml"))
    }
    return $args
}
