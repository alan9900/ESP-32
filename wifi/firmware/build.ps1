param([switch]$Upload, [string]$Port)
$ErrorActionPreference = 'Stop'
$savedUtf8 = $env:PYTHONUTF8
$savedEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $taskPython = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create the project .venv and install PlatformIO as described in README.md.' }
    $arguments = @('-m', 'platformio', 'run', '-j', '8', '--project-dir', $PSScriptRoot)
    if ($Upload) {
        $arguments += @('--target', 'upload')
        if ($Port) { $arguments += @('--upload-port', $Port) }
    }
    & $taskPython @arguments
    if ($LASTEXITCODE -ne 0) { throw "PlatformIO failed with exit code $LASTEXITCODE" }
} finally {
    $env:PYTHONUTF8 = $savedUtf8
    $env:PYTHONIOENCODING = $savedEncoding
}
