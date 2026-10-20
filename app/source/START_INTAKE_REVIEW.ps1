param([ValidateRange(1024,65535)][int]$Port = 8776)
$ErrorActionPreference = 'Stop'
$python = 'C:\Users\zhou\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Existing local Python is unavailable; no software will be installed.' }
Set-Location -LiteralPath $PSScriptRoot
Write-Host "Offline review only: http://127.0.0.1:$Port/"
Write-Host 'Existing ports 8765 / 8766 and their data are not used. No model or solver dispatch.'
& $python -B -X utf8 -m photonguard.workflow --data intake-preview-data --port $Port --offline-review
exit $LASTEXITCODE
