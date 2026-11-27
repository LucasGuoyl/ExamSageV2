param([Parameter(Mandatory=$true)][string]$Source,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$sourcePath=(Resolve-Path -LiteralPath $Source).Path
if ([IO.Path]::GetExtension($sourcePath) -ne '.pptx') { throw 'Only PPTX sources are accepted' }
$sourceHash=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$destination=[IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $destination) { throw 'Output already exists; use a new render directory' }
$stage=$destination+'.staging-'+[guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$ppt=$null
$deck=$null
$initialCount=0
try {
    $ppt=New-Object -ComObject PowerPoint.Application
    $initialCount=$ppt.Presentations.Count
    $oldSecurity=$ppt.AutomationSecurity
    $ppt.AutomationSecurity=3
    $deck=$ppt.Presentations.Open($sourcePath,-1,0,0)
    $width=2000
    $height=[int][Math]::Round($width*$deck.PageSetup.SlideHeight/$deck.PageSetup.SlideWidth)
    $slides=@()
    foreach ($slide in $deck.Slides) {
        $number=[int]$slide.SlideIndex
        $name="$number.png"
        $path=Join-Path $stage $name
        $slide.Export($path,'PNG',$width,$height)
        $slides+=@{number=$number;file=$name;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();width=$width;height=$height;hidden=($slide.SlideShowTransition.Hidden -eq -1);animation_steps=[int]$slide.TimeLine.MainSequence.Count}
    }
    if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHash) { throw 'Source changed during rendering' }
    $manifest=@{schema='native-slide-render-v1';source_sha256=$sourceHash;renderer="Microsoft PowerPoint $($ppt.Version)";render_mode='static_full_slide';page_count=[int]$deck.Slides.Count;slides=$slides}
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stage 'manifest.json') -Encoding utf8
    Move-Item -LiteralPath $stage -Destination $destination
    @{output=$destination;pages=$slides.Count;source_sha256=$sourceHash;animation_slides=@($slides | Where-Object animation_steps -GT 0).Count} | ConvertTo-Json
} finally {
    if ($null -ne $deck) { $deck.Close(); [Runtime.InteropServices.Marshal]::FinalReleaseComObject($deck) | Out-Null }
    if ($null -ne $ppt) {
        if ($null -ne $oldSecurity) { $ppt.AutomationSecurity=$oldSecurity }
        if ($initialCount -eq 0 -and $ppt.Presentations.Count -eq 0) { $ppt.Quit() }
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($ppt) | Out-Null
    }
}
