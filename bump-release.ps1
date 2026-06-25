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

.EXAMPLE
    .\bump-release.ps1
    .\bump-release.ps1 -Version 2.0.0 -Notes "Major redesign"
#>
param(
    [string]$Version = "",
    [string]$Notes   = "",
    [string]$Token   = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ── helpers ───────────────────────────────────────────────────────────────────

function Step { param([string]$msg)  Write-Host "`n── $msg" -ForegroundColor Cyan }
function OK   { param([string]$msg)  Write-Host "   OK  $msg" -ForegroundColor Green }
function Fail { param([string]$msg)  Write-Host "`n   !! $msg" -ForegroundColor Red; exit 1 }

function Update-File {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText(
        (Resolve-Path $Path).Path,
        $Content,
        [System.Text.UTF8Encoding]::new($false)   # UTF-8 sin BOM
    )
}

# ── 1. Detectar versión actual ─────────────────────────────────────────────────

Step "Detectando versión actual"

$pyContent = Get-Content "histogram.py" -Raw
if ($pyContent -notmatch 'APP_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"') {
    Fail "No se encontró APP_VERSION en histogram.py"
}
$major   = [int]$Matches[1]
$minor   = [int]$Matches[2]
$patch   = [int]$Matches[3]
$oldVer  = "$major.$minor.$patch"
$autoVer = "$major.$minor.$($patch + 1)"

OK "Versión instalada: $oldVer"

if ($Version -eq "") {
    $input = Read-Host "   Nueva versión [Enter = $autoVer]"
    $Version = if ($input -ne "") { $input } else { $autoVer }
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Fail "Formato de versión inválido: '$Version'  (usar MAJOR.MINOR.PATCH)"
}
if ($Version -eq $oldVer) {
    Fail "La versión nueva ($Version) es igual a la actual. Abortando."
}

OK "Nueva versión: $Version"

# ── 2. Actualizar histogram.py ────────────────────────────────────────────────

Step "Actualizando histogram.py"
$pyContent = $pyContent -replace 'APP_VERSION\s*=\s*"[\d\.]+"', "APP_VERSION = `"$Version`""
Update-File "histogram.py" $pyContent
OK "APP_VERSION = `"$Version`""

# ── 3. Actualizar installer.iss ───────────────────────────────────────────────

Step "Actualizando installer.iss"
$issContent = Get-Content "installer.iss" -Raw
$issContent = $issContent -replace '#define AppVersion\s+"[\d\.]+"', "#define AppVersion   `"$Version`""
Update-File "installer.iss" $issContent
OK "#define AppVersion `"$Version`""

# ── 4. Reconstruir ejecutable (PyInstaller) ───────────────────────────────────

Step "Reconstruyendo ejecutable con PyInstaller"
& ".venv\Scripts\pyinstaller.exe" "HistogramFAdeA.spec" --noconfirm
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller falló (exit $LASTEXITCODE)" }
OK "dist\HistogramFAdeA\HistogramFAdeA.exe generado"

# ── 5. Compilar instalador (Inno Setup) ──────────────────────────────────────

Step "Compilando instalador con Inno Setup"

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue)?.Source
if (-not $iscc) {
    @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 5\ISCC.exe"
    ) | ForEach-Object {
        if (-not $iscc -and (Test-Path $_)) { $iscc = $_ }
    }
}
if (-not $iscc) {
    Fail "Inno Setup (ISCC.exe) no encontrado.`n   Descárgalo en: https://jrsoftware.org/isdl.php"
}

& $iscc "installer.iss"
if ($LASTEXITCODE -ne 0) { Fail "Inno Setup falló (exit $LASTEXITCODE)" }

$assetPath = "installer_output\HistogramFAdeA_Setup_v$Version.exe"
if (-not (Test-Path $assetPath)) {
    Fail "Instalador no encontrado: $assetPath"
}
OK $assetPath

# ── 6. Git: commit, tag, push ─────────────────────────────────────────────────

Step "Git: commit, tag, push"

git add histogram.py installer.iss
git commit -m "bump version to $Version"
if ($LASTEXITCODE -ne 0) { Fail "git commit falló" }

git tag "v$Version"
if ($LASTEXITCODE -ne 0) { Fail "git tag falló (¿el tag v$Version ya existe?)" }

git push origin main --tags
if ($LASTEXITCODE -ne 0) { Fail "git push falló" }

OK "Tag v$Version enviado a origin"

# ── 7. Publicar GitHub Release ────────────────────────────────────────────────

Step "Publicando GitHub Release"

if ($Notes -eq "") {
    $Notes = Read-Host "   Notas del release (Enter para omitir)"
    if ($Notes -eq "") { $Notes = "HistogramFAdeA v$Version" }
}

$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
if ($ghCmd) {
    # ── gh CLI (si está instalado) ─────────────────────────────────────────
    gh release create "v$Version" $assetPath `
        --title "HistogramFAdeA v$Version" `
        --notes $Notes
    if ($LASTEXITCODE -ne 0) { Fail "gh release create falló" }
    OK "Release publicado con gh CLI"

} else {
    # ── GitHub REST API (fallback) ─────────────────────────────────────────
    if ($Token -eq "") {
        $Token = Read-Host "   GitHub Personal Access Token (scope: repo)"
    }

    $apiHeaders = @{
        Authorization          = "Bearer $Token"
        Accept                 = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    # Crear release
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

    # Subir asset
    $assetName  = [IO.Path]::GetFileName($assetPath)
    $uploadUri  = ($release.upload_url -replace '\{\?.*\}', '') +
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
