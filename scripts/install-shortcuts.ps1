# Creates "LOKI" and "Stop LOKI" shortcuts on your desktop (and a matching icon). Re-run any time.
#   powershell -ExecutionPolicy Bypass -File scripts\install-shortcuts.ps1

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
$Root = Split-Path -Parent $PSScriptRoot
$Icon = Join-Path $PSScriptRoot "loki.ico"

function New-OrbIcon([string]$path) {
    # A cyan orb on a dark disc, like LOKI's visualiser. Saved as a PNG-in-ICO (sharp at every size).
    $size = 256
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = "AntiAlias"
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.FillEllipse((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 7, 11, 20))), 4, 4, 248, 248)
    $g.DrawEllipse((New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(110, 94, 231, 255)), 6), 22, 22, 212, 212)
    $orb = New-Object System.Drawing.Drawing2D.GraphicsPath
    $orb.AddEllipse(48, 48, 160, 160)
    $brush = New-Object System.Drawing.Drawing2D.PathGradientBrush $orb
    $brush.CenterPoint = New-Object System.Drawing.PointF 108, 100
    $brush.CenterColor = [System.Drawing.Color]::FromArgb(255, 200, 248, 255)
    $brush.SurroundColors = @([System.Drawing.Color]::FromArgb(255, 24, 120, 150))
    $g.FillPath($brush, $orb)
    $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $png = $ms.ToArray()
    $out = New-Object System.IO.MemoryStream
    $w = New-Object System.IO.BinaryWriter $out
    $w.Write([UInt16]0); $w.Write([UInt16]1); $w.Write([UInt16]1)        # ICONDIR: reserved, type=icon, 1 image
    $w.Write([Byte]0); $w.Write([Byte]0); $w.Write([Byte]0); $w.Write([Byte]0)  # 256x256 (0 = 256), no palette
    $w.Write([UInt16]1); $w.Write([UInt16]32); $w.Write([UInt32]$png.Length); $w.Write([UInt32]22)
    $w.Write($png)
    [System.IO.File]::WriteAllBytes($path, $out.ToArray())
}

function New-Shortcut([string]$name, [string]$script, [string]$description, [string]$windowStyle) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $desktop "$name.lnk"))
    $lnk.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot $script)`""
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$Icon,0"
    $lnk.Description = $description
    $lnk.WindowStyle = $windowStyle  # 1 = normal, 7 = minimised
    $lnk.Save()
    Write-Host "Created $(Join-Path $desktop "$name.lnk")"
}

New-OrbIcon $Icon
New-Shortcut "LOKI" "start-loki.ps1" "Start LOKI and open it in the browser" 1
New-Shortcut "Stop LOKI" "stop-loki.ps1" "Stop LOKI and free the GPU" 7
