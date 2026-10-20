$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'PhotonGuard CONTINUE - Hidden Key'
Write-Host 'Continue the SAME semantic batch: 4 paid requests already consumed, total max 12, CNY limit 5.'
Write-Host 'Only undispatched second/third turns will continue. No first-turn restart or new ledger.'
& wsl.exe -d Ubuntu -u zhou --cd /home/zhou/projects/PhotonGuard --exec .runtime/run-python -B research/evaluation-coordinator/continue_live_small_batch.py
$continuationExitCode = $LASTEXITCODE
$continuationSession = Join-Path $PSScriptRoot 'local-validation/semantic-live-small-20261006'
@{ exit_code = $continuationExitCode; finished_utc = [DateTime]::UtcNow.ToString('o'); key_storage = 'MEMORY_ONLY' } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $continuationSession 'continuation-launcher-exit.json') -Encoding utf8
Write-Host ('Continuation exit code: ' + $continuationExitCode)
$null = Read-Host 'Press Enter to close this window'
