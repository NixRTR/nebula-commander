# Run ncclient at startup on Windows 11 (use with Task Scheduler or NSSM)
# 1. Install: pip install nebula-commander
# 2. Enroll once: ncclient enroll --server https://YOUR_SERVER --code XXXXXXXX
# 3. Edit the URL below (or set env NEBULA_COMMANDER_SERVER)
# 4. Task Scheduler: Create Task -> Trigger "At log on" -> Action: powershell -File "path\to\ncclient-run-windows.ps1"
#    Or run at system startup: Trigger "At startup", run with highest privileges, user SYSTEM or your account.

$env:NEBULA_COMMANDER_SERVER = "https://your-nebula-commander.example.com"
# Optional: $env:NEBULA_COMMANDER_OUTPUT_DIR = "$env:USERPROFILE\.nebula"
# Optional: $env:NEBULA_COMMANDER_INTERVAL = "60"

$ncclient = (Get-Command ncclient -ErrorAction SilentlyContinue).Source
if (-not $ncclient) {
    $ncclient = "$env:LOCALAPPDATA\Programs\Python\Python*\Scripts\ncclient.exe" -replace '\*', (Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Directory | Select-Object -First 1 -ExpandProperty Name)
    if (-not (Test-Path $ncclient)) {
        Write-Error "ncclient not found. Install with: pip install nebula-commander"
        exit 1
    }
}
& $ncclient run
