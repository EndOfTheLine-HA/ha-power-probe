# Generate the integration icon: a ring around a lightning bolt, on an amber tile.
Add-Type -AssemblyName System.Drawing
$outDir = Join-Path $PSScriptRoot '..\custom_components\power_probe\brand'
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

foreach ($size in @(256, 512)) {
    $bitmap = [Drawing.Bitmap]::new($size, $size)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $tile = [Drawing.Drawing2D.GraphicsPath]::new()
    $background = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(217, 119, 6))
    $white = [Drawing.SolidBrush]::new([Drawing.Color]::White)
    $ring = [Drawing.Pen]::new([Drawing.Color]::White, 11)
    $outline = [Drawing.Pen]::new([Drawing.Color]::White, 6)
    try {
        $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.Clear([Drawing.Color]::Transparent)
        $graphics.ScaleTransform(($size / 256.0), ($size / 256.0))
        $r = 56
        $tile.AddArc(12, 12, $r, $r, 180, 90)
        $tile.AddArc(244 - $r, 12, $r, $r, 270, 90)
        $tile.AddArc(244 - $r, 244 - $r, $r, $r, 0, 90)
        $tile.AddArc(12, 244 - $r, $r, $r, 90, 90)
        $tile.CloseFigure()
        $graphics.FillPath($background, $tile)
        $graphics.DrawEllipse($ring, 58, 58, 140, 140)
        $outline.LineJoin = [Drawing.Drawing2D.LineJoin]::Round
        $bolt = [Drawing.PointF[]]@(
            [Drawing.PointF]::new(146, 78), [Drawing.PointF]::new(104, 136),
            [Drawing.PointF]::new(126, 136), [Drawing.PointF]::new(112, 180),
            [Drawing.PointF]::new(154, 120), [Drawing.PointF]::new(132, 120)
        )
        $graphics.FillPolygon($white, $bolt)
        $graphics.DrawPolygon($outline, $bolt)
        $filename = if ($size -eq 256) { 'icon.png' } else { 'icon@2x.png' }
        $bitmap.Save((Join-Path $outDir $filename), [Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $outline.Dispose()
        $ring.Dispose()
        $white.Dispose()
        $background.Dispose()
        $tile.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}
