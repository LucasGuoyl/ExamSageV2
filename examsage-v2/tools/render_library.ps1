param([string]$Data='data')
$ErrorActionPreference='Stop'
$dataRoot=(Resolve-Path -LiteralPath $Data).Path
$registry=Get-Content -LiteralPath (Join-Path $dataRoot 'library.json') -Raw | ConvertFrom-Json
$results=@()
foreach($course in $registry.courses){
    $courseRoot=[IO.Path]::GetFullPath((Join-Path $dataRoot $course.data))
    if(-not $courseRoot.StartsWith($dataRoot+[IO.Path]::DirectorySeparatorChar)){throw 'Course path escapes data root'}
    $manifest=Get-Content -LiteralPath (Join-Path $courseRoot 'manifest.json') -Raw | ConvertFrom-Json
    foreach($doc in $manifest.documents){
        if(-not $doc.relative_path.EndsWith('.pptx')){continue}
        $source=Join-Path (Join-Path $courseRoot 'assets') $doc.asset
        $output=Join-Path (Join-Path $courseRoot 'slide-renders') $doc.sha256
        if(Test-Path -LiteralPath (Join-Path $output 'manifest.json')){continue}
        try{
            & (Join-Path $PSScriptRoot 'render_pptx.ps1') -Source $source -Output $output
            $results+=@{course=$course.slug;document=$doc.id;status='rendered';pages=$doc.pages}
        }catch{
            $results+=@{course=$course.slug;document=$doc.id;status='failed';error=$_.Exception.Message}
            Write-Warning "$($doc.relative_path): $($_.Exception.Message)"
        }
    }
}
$results | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $dataRoot 'slide-render-report.json') -Encoding utf8
