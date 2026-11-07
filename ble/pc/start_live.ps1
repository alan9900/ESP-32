param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskScript = Join-Path $PSScriptRoot 'auto_live.py'
if (-not $PythonPath) {
    $taskCandidates = @(
        (Join-Path $taskRoot '.venv\Scripts\python.exe'),
        (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
        (Join-Path $taskRoot '.project_storage\temp\codex-esp32-ble-venv\Scripts\python.exe')
    )
    $PythonPath = $taskCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Create a Python virtual environment with bleak installed, or pass -PythonPath.'
}
$taskMatches = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -and
    $_.CommandLine.IndexOf($taskScript, [StringComparison]::OrdinalIgnoreCase) -ge 0
})
if ($taskMatches.Count -gt 0) {
    Write-Host 'Bluetooth display sender is already running.'
    return
}
$taskStorage = Join-Path $taskRoot '.project_storage\ble'
New-Item -ItemType Directory -Path $taskStorage -Force | Out-Null
$taskOutput = Join-Path $taskStorage 'sender.out.log'
$taskError = Join-Path $taskStorage 'sender.err.log'
$taskProcess = Start-Process -FilePath $PythonPath -ArgumentList @('"' + $taskScript + '"') `
    -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $taskOutput `
    -RedirectStandardError $taskError -PassThru
$taskProcess.Id | Set-Content -LiteralPath (Join-Path $taskStorage 'sender.pid')
Write-Host 'Bluetooth display sender started. Status log:' $taskOutput
