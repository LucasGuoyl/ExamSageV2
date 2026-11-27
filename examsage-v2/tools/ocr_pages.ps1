param([string]$Inventory='data/qa/low-text-20261028/inventory.json',[int]$Limit=0)
$ErrorActionPreference='Stop'
if($PSVersionTable.PSEdition -eq 'Core'){throw 'Run this offline OCR script with Windows PowerShell 5.1.'}
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
$taskMethod=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'} | Select-Object -First 1
function Await-Operation($Operation,[Type]$ResultType){
    $task=$taskMethod.MakeGenericMethod($ResultType).Invoke($null,@($Operation))
    $task.Wait()
    return $task.Result
}
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if(-not $engine){throw 'No local OCR recognizer language available'}
$inventoryPath=(Resolve-Path -LiteralPath $Inventory).Path
$output=Join-Path (Split-Path -Parent $inventoryPath) 'ocr'
$entries=Get-Content -LiteralPath $inventoryPath -Raw -Encoding utf8 | ConvertFrom-Json
if($Limit -gt 0){$entries=@($entries | Select-Object -First $Limit)}
$complete=0
foreach($entry in $entries){
    $folder=Join-Path $output $entry.course
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $dest=Join-Path $folder "$($entry.document_id)-p$($entry.number).json"
    if(Test-Path -LiteralPath $dest){$complete++;continue}
    $stream=$null;$bitmap=$null
    try{
        $hash=(Get-FileHash -LiteralPath $entry.image -Algorithm SHA256).Hash.ToLowerInvariant()
        if($hash -ne $entry.render_sha256){throw 'Input image hash mismatch'}
        $file=Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($entry.image)) ([Windows.Storage.StorageFile])
        $stream=Await-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder=Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap=Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $recognized=Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines=@()
        foreach($line in $recognized.Lines){
            $words=@()
            foreach($word in $line.Words){
                $rect=$word.BoundingRect
                $words+=@{text=$word.Text;bbox=@(($rect.X/$entry.width),($rect.Y/$entry.height),(($rect.X+$rect.Width)/$entry.width),(($rect.Y+$rect.Height)/$entry.height))}
            }
            $lines+=@{text=($words.text -join ' ');words=$words}
        }
        $record=@{schema='page-ocr-v1';source_sha256=$entry.source_sha256;render_sha256=$hash;number=$entry.number;
            engine='Windows.Media.Ocr';language=$engine.RecognizerLanguage.LanguageTag;status='recognized';
            text=($lines.text -join "`n");lines=$lines;review='machine_checked'}
    }catch{
        $record=@{schema='page-ocr-v1';source_sha256=$entry.source_sha256;render_sha256=$entry.render_sha256;number=$entry.number;status='failed';error=$_.Exception.Message}
    }finally{
        if($bitmap){$bitmap.Dispose()};if($stream){$stream.Dispose()}
    }
    $record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $dest -Encoding utf8
    $complete++
    if($complete % 10 -eq 0 -or $Limit -gt 0){Write-Output "OCR $complete / $($entries.Count): $($record.status)"}
}
Write-Output "OCR completed: $complete, language: $($engine.RecognizerLanguage.LanguageTag)"
