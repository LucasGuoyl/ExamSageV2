param(
    [ValidateSet('serve','student','build','build-library','test','evaluate','status')][string]$Action = 'serve',
    [int]$Port = 8766,
    [string]$PythonPath = '',
    [switch]$Reload
)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$parentDir = Split-Path -Parent $projectDir
Set-Location -LiteralPath $projectDir
if (-not $PythonPath) {
    $candidates = @(
        $env:EXAMSAGE_PYTHON,
        (Join-Path $projectDir '.venv/Scripts/python.exe'),
        (Join-Path $parentDir '.worktrees/agent-kernel/.venv/Scripts/python.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { $PythonPath = $candidate; break }
    }
}
if (-not $PythonPath) { throw 'Python runtime not found. Create .venv and install: python -m pip install -e ".[dev]". Or set EXAMSAGE_PYTHON.' }
$env:PYTHONPATH = Join-Path $projectDir 'src'
$env:PYTHONUTF8 = '1'
if ($Action -eq 'test') {
    $testRoot = Join-Path $projectDir 'data/test-runs'
    New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
    $testPath = Join-Path $testRoot ([guid]::NewGuid().ToString('N'))
    & $PythonPath -X utf8 -m pytest --basetemp=$testPath --tb=short
} elseif ($Action -eq 'build-library') {
    & $PythonPath -X utf8 -m examsage build-library --source (Join-Path $parentDir 'files/exam_predictor/exam_predictor/data_samples') --audit (Join-Path $parentDir 'output/course-audit/2026-10-25-course-inventory.json') --config 'courses/library.json' --data 'data'
} elseif ($Action -eq 'build') {
    & $PythonPath -X utf8 -m examsage build --source (Join-Path $parentDir 'files/exam_predictor/exam_predictor/data_samples/grt') --audit (Join-Path $parentDir 'output/course-audit/2026-10-25-course-inventory.json') --recipe 'courses/grt.json' --data 'data/grt'
} elseif ($Action -eq 'evaluate') {
    & $PythonPath -X utf8 -m examsage evaluate --data 'data/grt' --cases 'evaluation/grt_cases.json' --benchmark
} elseif ($Action -eq 'status') {
    & $PythonPath -X utf8 -m examsage status --data 'data/grt'
} elseif ($Action -eq 'student') {
    if (-not $PSBoundParameters.ContainsKey('Port')) { $Port = 8769 }
    Write-Host "ExamSage student: http://127.0.0.1:$Port"
    & $PythonPath -X utf8 -m examsage serve-student --port $Port
} else {
    if (-not (Test-Path -LiteralPath 'data/grt/current.json')) {
        & $PythonPath -X utf8 -m examsage build --source (Join-Path $parentDir 'files/exam_predictor/exam_predictor/data_samples/grt') --audit (Join-Path $parentDir 'output/course-audit/2026-10-25-course-inventory.json') --recipe 'courses/grt.json' --data 'data/grt'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    Write-Host "ExamSage v2: http://127.0.0.1:$Port"
    if ($Reload) {
        & $PythonPath -X utf8 -m uvicorn examsage.devserver:create_app --factory --host 127.0.0.1 --port $Port --reload --reload-dir (Join-Path $projectDir 'src/examsage')
    } else {
        & $PythonPath -X utf8 -m examsage serve --data 'data/grt' --port $Port
    }
}
exit $LASTEXITCODE
