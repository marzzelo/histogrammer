<#
.SYNOPSIS
    Bump version, rebuild installer, and publish a new GitHub release.

.DESCRIPTION
    1. Bumps the patch version in histogram.py and installer.iss
    2. Rebuilds the PyInstaller executable
    3. Compiles the Inno Setup installer
    4. Commits, tags, and pushes to GitHub
    5. Creates a GitHub release and uploads the installer asset

.PARAMETER Version
    Explicit version string (e.g. "1.3.0"). If omitted, patch number is auto-incremented.

.PARAMETER Notes
    Release notes text. If omitted, prompted interactively.

.PARAMETER Token
    GitHub Personal Access Token (required only if 'gh' CLI is not installed).

.PARAMETER InnoSetupPath
    Full path to ISCC.exe if not in PATH or standard install locations.
    Example: -InnoSetupPath "C:\Tools\InnoSetup6\ISCC.exe"

.EXAMPLE
    .\bump-release.ps1
    .\bump-release.ps1 -Version 2.0.0 -Notes "Major redesign"
    .\bump-release.ps1 -InnoSetupPath "C:\InnoSetup6\ISCC.exe"
#>
param(
    [string]$Version       = "",
    [string]$Notes         = "",
    [string]$Token         = "",
    [string]$InnoSetupPath = ""
)

# Forzar UTF-8 en la consola para que los caracteres especiales se muestren bien
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ── helpers ───────────────────────────────────────────────────────────────────

function Step { param([string]$msg)  Write-Host "`n-- $msg" -ForegroundColor Cyan }
function OK   { param([string]$msg)  Write-Host "   OK  $msg" -ForegroundColor Green }
function Fail { param([string]$msg)  Write-Host "`n   !! $msg" -ForegroundColor Red; exit 1 }

function Update-File {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText(
        (Resolve-Path $Path).Path,
        $Content,
        [System.Text.UTF8Encoding]::new($false)
    )
}

# ── 1. Detectar version actual ────────────────────────────────────────────────

Step "Detectando version actual"

$pyContent = [System.IO.File]::ReadAllText((Resolve-Path "histogram.py").Path, [System.Text.UTF8Encoding]::new($false))
if ($pyContent -notmatch 'APP_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"') {
    Fail "No se encontro APP_VERSION en histogram.py"
}
$major   = [int]$Matches[1]
$minor   = [int]$Matches[2]
$patch   = [int]$Matches[3]
$oldVer  = "$major.$minor.$patch"
$autoVer = "$major.$minor.$($patch + 1)"

OK "Version actual: $oldVer"

if ($Version -eq "") {
    $userInput = Read-Host "   Nueva version [Enter = $autoVer]"
    $Version = if ($userInput -ne "") { $userInput } else { $autoVer }
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Fail "Formato invalido: '$Version'  (usar MAJOR.MINOR.PATCH)"
}
if ($Version -eq $oldVer) {
    Fail "La version nueva ($Version) es igual a la actual. Abortando."
}

OK "Nueva version: $Version"

# ── 2. Actualizar histogram.py ────────────────────────────────────────────────

Step "Actualizando histogram.py"
$pyContent = $pyContent -replace 'APP_VERSION\s*=\s*"[\d\.]+"', "APP_VERSION = `"$Version`""
Update-File "histogram.py" $pyContent
OK "APP_VERSION = `"$Version`""

# ── 3. Actualizar installer.iss ───────────────────────────────────────────────

Step "Actualizando installer.iss"
$issContent = [System.IO.File]::ReadAllText((Resolve-Path "installer.iss").Path, [System.Text.UTF8Encoding]::new($false))
$issContent = $issContent -replace '#define AppVersion\s+"[\d\.]+"', "#define AppVersion   `"$Version`""
Update-File "installer.iss" $issContent
OK "#define AppVersion `"$Version`""

# ── 4. Reconstruir ejecutable (PyInstaller) ───────────────────────────────────

Step "Reconstruyendo ejecutable con PyInstaller"
& ".venv\Scripts\pyinstaller.exe" "HistogramFAdeA.spec" --noconfirm
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller fallo (exit $LASTEXITCODE)" }
OK "dist\HistogramFAdeA\HistogramFAdeA.exe generado"

# ── 5. Compilar instalador (Inno Setup) ──────────────────────────────────────

Step "Compilando instalador con Inno Setup"

$iscc = $null

# Prioridad 1: parametro -InnoSetupPath
if ($InnoSetupPath -ne "") {
    if (Test-Path $InnoSetupPath) { $iscc = $InnoSetupPath }
    else { Fail "ISCC.exe no encontrado en la ruta indicada: $InnoSetupPath" }
}

# Prioridad 2: en el PATH del sistema
if (-not $iscc) {
    $isccCmd = Get-Command ISCC -ErrorAction SilentlyContinue
    if ($isccCmd) { $iscc = $isccCmd.Source }
}

# Prioridad 3: rutas de instalacion estandar
if (-not $iscc) {
    $candidates = @(
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 5\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
        "C:\InnoSetup7\ISCC.exe",
        "C:\InnoSetup6\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $iscc = $c; break }
    }
}

if (-not $iscc) {
    Write-Host ""
    Write-Host "   Inno Setup (ISCC.exe) no encontrado." -ForegroundColor Yellow
    Write-Host "   Opciones:" -ForegroundColor Yellow
    Write-Host "     1) Instalarlo desde https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    Write-Host "     2) Ejecutar con: .\bump-release.ps1 -InnoSetupPath `"C:\ruta\ISCC.exe`"" -ForegroundColor Yellow
    Write-Host ""
    $manualPath = Read-Host "   O ingresa la ruta completa a ISCC.exe ahora (Enter para cancelar)"
    if ($manualPath -eq "" -or -not (Test-Path $manualPath)) {
        Fail "ISCC.exe no disponible. Abortando."
    }
    $iscc = $manualPath
}

OK "Usando: $iscc"
& $iscc "installer.iss"
if ($LASTEXITCODE -ne 0) { Fail "Inno Setup fallo (exit $LASTEXITCODE)" }

$assetPath = "installer_output\HistogramFAdeA_Setup_v$Version.exe"
if (-not (Test-Path $assetPath)) {
    Fail "Instalador no encontrado: $assetPath"
}
OK $assetPath

# ── 6. Git: commit, tag, push ─────────────────────────────────────────────────

Step "Git: commit, tag, push"

git add histogram.py installer.iss
git commit -m "bump version to $Version"
if ($LASTEXITCODE -ne 0) { Fail "git commit fallo" }

git tag "v$Version"
if ($LASTEXITCODE -ne 0) { Fail "git tag fallo (el tag v$Version ya existe?)" }

# Detectar nombre del remote (tipicamente 'origin' o 'main')
$remote = git remote 2>$null | Select-Object -First 1
if (-not $remote) { Fail "No se encontro ningun git remote configurado" }
OK "Remote: $remote"

git push $remote HEAD --tags
if ($LASTEXITCODE -ne 0) { Fail "git push fallo" }

OK "Tag v$Version enviado a origin"

# ── 7. Publicar GitHub Release ────────────────────────────────────────────────

Step "Publicando GitHub Release"

if ($Notes -eq "") {
    $Notes = Read-Host "   Notas del release (Enter para omitir)"
    if ($Notes -eq "") { $Notes = "HistogramFAdeA v$Version" }
}

$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
if ($ghCmd) {
    gh release create "v$Version" $assetPath `
        --title "HistogramFAdeA v$Version" `
        --notes $Notes
    if ($LASTEXITCODE -ne 0) { Fail "gh release create fallo" }
    OK "Release publicado con gh CLI"

} else {
    if ($Token -eq "") {
        $Token = Read-Host "   GitHub Personal Access Token (scope: repo)"
    }

    $apiHeaders = @{
        Authorization          = "Bearer $Token"
        Accept                 = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    $releaseBody = @{
        tag_name   = "v$Version"
        name       = "HistogramFAdeA v$Version"
        body       = $Notes
        draft      = $false
        prerelease = $false
    } | ConvertTo-Json -Compress

    $release = Invoke-RestMethod `
        -Uri "https://api.github.com/repos/marzzelo/histogrammer/releases" `
        -Method Post `
        -Headers $apiHeaders `
        -Body $releaseBody `
        -ContentType "application/json"

    OK "Release creado: $($release.html_url)"

    $assetName = [IO.Path]::GetFileName($assetPath)
    $uploadUri = ($release.upload_url -replace '\{\?.*\}', '') +
                 "?name=$([uri]::EscapeDataString($assetName))"

    $uploadHeaders = @{
        Authorization          = "Bearer $Token"
        Accept                 = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "Content-Type"         = "application/octet-stream"
    }

    Invoke-RestMethod `
        -Uri $uploadUri `
        -Method Post `
        -Headers $uploadHeaders `
        -InFile (Resolve-Path $assetPath).Path | Out-Null

    OK "Asset subido: $assetName"
}

# ── Resumen ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  Release v$Version publicado exitosamente." -ForegroundColor Green
Write-Host "  https://github.com/marzzelo/histogrammer/releases/tag/v$Version"
Write-Host ""
