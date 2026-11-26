param([switch]$DesktopShortcut)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required. Install Python and run Setup.cmd again.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the internet connection.' }
& (Join-Path $PSScriptRoot 'create-shortcut.ps1') -DesktopShortcut:$DesktopShortcut
Write-Host 'Ready. Open ML Trainer.lnk or Start.vbs.'
