<#
.SYNOPSIS
  One-shot Windows build: fetch tools -> PyInstaller -> Inno Setup installer.

.DESCRIPTION
  Produces:
    dist\YT Downloader\                      (standalone app folder)
    packaging\dist_installer\YT-Downloader-Setup.exe   (the installer)

.PARAMETER SkipTools
  Skip downloading ffmpeg/aria2c (use whatever is already in packaging\vendor\bin).

.PARAMETER SkipInstaller
  Build the app folder only; don't run Inno Setup.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
param(
  [switch]$SkipTools,
  [switch]$SkipInstaller,
  [string]$CertPath,        # optional .pfx code-signing certificate
  [string]$CertPassword     # password for the .pfx
)

function Sign($file) {
  if (-not $CertPath) { return }
  $st = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if (-not $st) {
    Write-Warning "signtool.exe not found (install the Windows SDK) - skipping signing."
    return
  }
  & $st.Source sign /f $CertPath /p $CertPassword /fd SHA256 `
    /tr http://timestamp.digicert.com /td SHA256 $file
}

$ErrorActionPreference = "Stop"
# CRITICAL: Invoke-WebRequest is 10-100x slower while it renders a progress bar
# in Windows PowerShell 5.1. Disabling progress makes large downloads fast.
$ProgressPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot   # project root
$pkg = $PSScriptRoot
$vendorBin = Join-Path $pkg "vendor\bin"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

function Download($url, $out) {
  # Prefer .NET WebClient (fast, no progress overhead); fall back to IWR.
  try {
    (New-Object System.Net.WebClient).DownloadFile($url, $out)
  } catch {
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
  }
}

# --- 1. Fetch ffmpeg + aria2c -------------------------------------------------
if (-not $SkipTools) {
  Step "Downloading ffmpeg and aria2c"
  New-Item -ItemType Directory -Force -Path $vendorBin | Out-Null
  $tmp = Join-Path $env:TEMP "ytdl-vendor"
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null

  $ffZip = Join-Path $tmp "ffmpeg.zip"
  $ffUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
  Write-Host "  ffmpeg: $ffUrl"
  Download $ffUrl $ffZip
  Expand-Archive -Path $ffZip -DestinationPath (Join-Path $tmp "ffmpeg") -Force
  Get-ChildItem -Path (Join-Path $tmp "ffmpeg") -Recurse -Include ffmpeg.exe, ffprobe.exe |
    ForEach-Object { Copy-Item $_.FullName -Destination $vendorBin -Force }

  $arZip = Join-Path $tmp "aria2.zip"
  $arUrl = "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip"
  Write-Host "  aria2c: $arUrl"
  Download $arUrl $arZip
  Expand-Archive -Path $arZip -DestinationPath (Join-Path $tmp "aria2") -Force
  Get-ChildItem -Path (Join-Path $tmp "aria2") -Recurse -Include aria2c.exe |
    ForEach-Object { Copy-Item $_.FullName -Destination $vendorBin -Force }

  Write-Host "  vendored binaries:" -ForegroundColor Green
  Get-ChildItem $vendorBin | ForEach-Object { Write-Host "    $($_.Name)" }
} else {
  Step "Skipping tool download (using existing packaging\vendor\bin)"
}

# --- 2. PyInstaller build -----------------------------------------------------
Step "Building app with PyInstaller"
Push-Location $root
try {
  uv run --with pyinstaller pyinstaller (Join-Path $pkg "yt-downloader.spec") --noconfirm --clean
} finally {
  Pop-Location
}
$appDir = Join-Path $root "dist\YT Downloader"
if (-not (Test-Path (Join-Path $appDir "YT Downloader.exe"))) {
  throw "PyInstaller build did not produce the expected exe."
}
Write-Host "  built: $appDir" -ForegroundColor Green
Sign (Join-Path $appDir "YT Downloader.exe")

# --- 3. Inno Setup installer --------------------------------------------------
if ($SkipInstaller) {
  Step "Skipping installer (app folder is ready in dist\YT Downloader)"
  return
}

Step "Compiling installer with Inno Setup"
$iscc = $null
foreach ($c in @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LocalAppData}\Programs\Inno Setup 6\ISCC.exe")) {
  if (Test-Path $c) { $iscc = $c; break }
}
if (-not $iscc) {
  $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if ($cmd) { $iscc = $cmd.Source }
}

if (-not $iscc) {
  Write-Warning "Inno Setup (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php"
  Write-Warning "Then run:  iscc packaging\installer.iss"
  return
}

& $iscc (Join-Path $pkg "installer.iss")
$setup = Join-Path $pkg "dist_installer\YT-Downloader-Setup.exe"
if (Test-Path $setup) {
  Sign $setup
  Write-Host "`nDONE. Installer: $setup" -ForegroundColor Green
}
