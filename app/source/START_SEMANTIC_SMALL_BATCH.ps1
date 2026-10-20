$ErrorActionPreference = 'Stop'
Write-Host 'PhotonGuard: A0/A1 initial observations, DeepSeek Flash, max 12 paid requests, CNY 5.'
Write-Host 'Enter the key only at the hidden Ubuntu prompt; do not paste it into chat.'
& wsl.exe -d Ubuntu -u zhou --cd /home/zhou/projects/PhotonGuard --exec .runtime/run-python -B research/evaluation-coordinator/run_live_small_batch.py --plan /home/zhou/projects/PhotonGuard/local-validation/semantic-live-small-20261006/plan.json
$batchExitCode = $LASTEXITCODE
$batchSession = Join-Path $PSScriptRoot 'local-validation/semantic-live-small-20261006'
@{ exit_code = $batchExitCode; finished_utc = [DateTime]::UtcNow.ToString('o'); key_storage = 'MEMORY_ONLY' } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $batchSession 'launcher-exit.json') -Encoding utf8
Write-Host ('Runner exit code: ' + $batchExitCode)
$null = Read-Host 'Press Enter to close this window'
