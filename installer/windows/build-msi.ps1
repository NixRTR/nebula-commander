# Build Nebula Commander MSI. Run from installer/windows/.
# Requires: WiX 5, and redist/ncclient.exe + redist/ncclient-tray.exe + redist/ncclient-service.exe
# Usage: .\build-msi.ps1 [-Version "0.1.12"]

param(
    [string]$Version = "0.0.0"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$redist = Join-Path $ScriptDir "redist"
foreach ($exe in @("ncclient.exe", "ncclient-tray.exe", "ncclient-service.exe")) {
    $path = Join-Path $redist $exe
    if (-not (Test-Path $path)) {
        Write-Error "Missing $path - copy ncclient and ncclient-tray exes into redist/"
    }
}

$out = "NebulaCommander-windows-amd64.msi"
& wix build Product.wxs -ext WixToolset.Util.wixext -ext WixToolset.UI.wixext -o $out -d "Version=$Version" -arch x64
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Built $out"
