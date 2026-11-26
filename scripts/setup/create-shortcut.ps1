param(
    [switch]$DesktopShortcut,
    [ValidatePattern('^[A-Za-z0-9_-]+@[A-Za-z0-9._-]+$')][string]$VpsTarget
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$iconPath = Join-Path $projectRoot 'web/mockroom.ico'
$shell = New-Object -ComObject WScript.Shell
$name = 'ML Trainer.lnk'
$arguments = '"' + (Join-Path $projectRoot 'launcher.pyw') + '"'
$description = 'ML Trainer - Windows desktop application'
if ($VpsTarget) {
    $name = 'ML Trainer ' + [char]0x2014 + ' VPS.lnk'
    $arguments += ' --vps ' + $VpsTarget
    $description = 'ML Trainer - connect to VPS over SSH'
}
$targets = @((Join-Path $projectRoot $name))
if ($DesktopShortcut) {
    $desktopTarget = Join-Path ([Environment]::GetFolderPath('Desktop')) $name
    if ($VpsTarget) { $targets = @($desktopTarget) } else { $targets += $desktopTarget }
}
foreach ($target in $targets) {
    $shortcut = $shell.CreateShortcut($target)
    $shortcut.TargetPath = Join-Path $projectRoot '.venv/Scripts/pythonw.exe'
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = $iconPath
    $shortcut.WindowStyle = 7
    $shortcut.Description = $description
    $shortcut.Save()
    Write-Host "Created: $target"
}
