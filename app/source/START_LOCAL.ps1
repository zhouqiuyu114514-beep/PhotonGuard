param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Write-Host "PhotonGuard evidence viewer: http://127.0.0.1:$Port/"
Write-Host 'Press Ctrl+C to stop. If the viewer is already running, open the URL directly.'
& wsl.exe -d Ubuntu -u zhou --cd /home/zhou/projects/PhotonGuard --exec .runtime/run-python -m photonguard ui --root . --port $Port
exit $LASTEXITCODE
