$ErrorActionPreference = 'Stop'
Write-Host 'Single DeepSeek diagnostic. Enter the key only in the hidden prompt below.'
& wsl.exe -d Ubuntu -u zhou --cd /home/zhou/projects/PhotonGuard --exec .runtime/run-python -B tools/run_deepseek_once.py
Write-Host "Process exit: $LASTEXITCODE. Return to Codex; no second paid request should be started."
Read-Host 'Press Enter to close'
