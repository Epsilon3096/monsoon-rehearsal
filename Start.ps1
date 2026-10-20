param([int]$Port = 8513, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$workspacePython = Join-Path $PSScriptRoot '..\..\work\runtime\venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) {
    $appPython = $localPython
} elseif (Test-Path -LiteralPath $workspacePython) {
    $appPython = (Resolve-Path -LiteralPath $workspacePython).Path
} else {
    Write-Host 'Preparing the local Python environment. Python 3.11 to 3.13 is required.'
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $bootstrapPython = $null
        foreach ($pythonVersion in @('3.13', '3.12', '3.11')) {
            $candidatePython = & py "-$pythonVersion" -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) { $bootstrapPython = $candidatePython; break }
        }
        if (-not $bootstrapPython) { throw 'Install Python 3.11, 3.12 or 3.13, then run again.' }
        & $bootstrapPython -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else {
        throw 'Install Python 3.11, 3.12 or 3.13, then run this launcher again.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    $appPython = $localPython
    & $appPython -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'This prototype requires Python 3.11 to 3.13.' }
    & $appPython -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
Write-Host "Monsoon Rehearsal: http://127.0.0.1:$Port"
Write-Host 'Keep this window open. Press Ctrl+C to stop the local prototype.'
$headless = if ($NoBrowser) { 'true' } else { 'false' }
& $appPython -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port --server.headless $headless
exit $LASTEXITCODE
