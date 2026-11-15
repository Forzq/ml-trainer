param([switch]$DesktopShortcut)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$iconPath = Join-Path $projectRoot 'web/app.ico'
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap 64,64
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.Clear([System.Drawing.ColorTranslator]::FromHtml('#24483e'))
$font = New-Object System.Drawing.Font 'Segoe UI',25,([System.Drawing.FontStyle]::Bold)
$brush = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#e0edc9'))
$graphics.DrawString('ml', $font, $brush, 6, 9)
$iconHandle = $bitmap.GetHicon()
$icon = [System.Drawing.Icon]::FromHandle($iconHandle)
$stream = [System.IO.File]::Create($iconPath)
try { $icon.Save($stream) } finally { $stream.Dispose(); $icon.Dispose(); $brush.Dispose(); $font.Dispose(); $graphics.Dispose(); $bitmap.Dispose() }
$shell = New-Object -ComObject WScript.Shell
$targets = @((Join-Path $projectRoot 'ML Trainer.lnk'))
if ($DesktopShortcut) { $targets += Join-Path ([Environment]::GetFolderPath('Desktop')) 'ML Trainer.lnk' }
foreach ($target in $targets) {
    $shortcut = $shell.CreateShortcut($target)
    $shortcut.TargetPath = Join-Path $projectRoot '.venv/Scripts/pythonw.exe'
    $shortcut.Arguments = '"' + (Join-Path $projectRoot 'launcher.pyw') + '"'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = $iconPath
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'ML Trainer - Windows desktop application'
    $shortcut.Save()
    Write-Host "Created: $target"
}
