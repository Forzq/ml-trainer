param([switch]$DesktopShortcut)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$iconPath = Join-Path $projectRoot 'web/app-purple.ico'
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap 256,256
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$shape = New-Object System.Drawing.Drawing2D.GraphicsPath
$shape.AddArc(4, 4, 80, 80, 180, 90)
$shape.AddArc(172, 4, 80, 80, 270, 90)
$shape.AddArc(172, 172, 80, 80, 0, 90)
$shape.AddArc(4, 172, 80, 80, 90, 90)
$shape.CloseFigure()
$gradient = New-Object System.Drawing.Drawing2D.LinearGradientBrush ([System.Drawing.Point]::new(0, 0)), ([System.Drawing.Point]::new(256, 256)), ([System.Drawing.ColorTranslator]::FromHtml('#a855f7')), ([System.Drawing.ColorTranslator]::FromHtml('#5b21b6'))
$graphics.FillPath($gradient, $shape)
$font = New-Object System.Drawing.Font 'Segoe UI',112,([System.Drawing.FontStyle]::Bold),([System.Drawing.GraphicsUnit]::Pixel)
$brush = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#faf5ff'))
$format = New-Object System.Drawing.StringFormat
$format.Alignment = [System.Drawing.StringAlignment]::Center
$format.LineAlignment = [System.Drawing.StringAlignment]::Center
$graphics.DrawString('ml', $font, $brush, ([System.Drawing.RectangleF]::new(0, -4, 256, 256)), $format)
# PNG frames keep the icon sharp at different Windows display scales.
$frames = @(foreach ($size in @(16, 24, 32, 48, 64, 128, 256)) {
    $frame = New-Object System.Drawing.Bitmap $size,$size
    $frameGraphics = [System.Drawing.Graphics]::FromImage($frame)
    $frameGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $frameGraphics.DrawImage($bitmap, 0, 0, $size, $size)
    $memory = New-Object System.IO.MemoryStream
    try {
        $frame.Save($memory, [System.Drawing.Imaging.ImageFormat]::Png)
        [PSCustomObject]@{ Size = $size; Bytes = $memory.ToArray() }
    } finally { $memory.Dispose(); $frameGraphics.Dispose(); $frame.Dispose() }
})
$writer = New-Object System.IO.BinaryWriter ([System.IO.File]::Create($iconPath))
try {
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$frames.Count)
    $offset = 6 + 16 * $frames.Count
    foreach ($frame in $frames) {
        $dimension = [byte]($frame.Size % 256)
        $writer.Write($dimension); $writer.Write($dimension)
        $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32)
        $writer.Write([uint32]$frame.Bytes.Length); $writer.Write([uint32]$offset)
        $offset += $frame.Bytes.Length
    }
    foreach ($frame in $frames) { $writer.Write([byte[]]$frame.Bytes) }
} finally {
    $writer.Dispose(); $format.Dispose(); $brush.Dispose(); $font.Dispose()
    $gradient.Dispose(); $shape.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
}
# Keep the native window icon in sync; a new shortcut path also avoids stale icon caches.
Copy-Item -LiteralPath $iconPath -Destination (Join-Path $projectRoot 'web/app.ico') -Force
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
