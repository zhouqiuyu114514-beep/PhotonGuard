param(
    [Parameter(Mandatory=$true)][string]$ProjectPath,
    [string]$Distribution = 'Ubuntu',
    [string]$RuntimeCommand = '.runtime/run-python',
    [ValidateRange(1024,65535)][int]$Port = 8766
)
$ErrorActionPreference = 'Stop'
Write-Host "PhotonGuard graphical workflow: http://127.0.0.1:$Port/"
Write-Host 'This launcher does not copy or modify your source, install dependencies, or approve tasks.'
Write-Host 'Use the reviewed NEW Linux source directory as ProjectPath. Press Ctrl+C to stop the UI.'
& wsl.exe --distribution $Distribution --cd $ProjectPath --exec $RuntimeCommand -m photonguard.workflow --data workflow-data --port $Port
exit $LASTEXITCODE
