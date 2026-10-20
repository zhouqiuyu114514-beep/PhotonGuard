param([Parameter(ValueFromRemainingArguments=$true)][string[]]$ForwardArguments)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$distributionArgs = @()
if ($projectRoot -match '^\\\\wsl(?:\.localhost|\$)\\([^\\]+)\\(.*)$') {
    $distributionArgs = @('--distribution', $Matches[1])
    $linuxProject = '/' + $Matches[2].Replace('\', '/')
} else {
    $linuxProject = (& wsl.exe --exec wslpath -a $projectRoot).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'WSL path conversion failed; install WSL and the documented solver environment first.' }
}
$runtimeScript = @'
from pathlib import Path
r=Path.cwd()
options=[r/'.runtime/run-python',r.parent/'PhotonGuard/.runtime/run-python']
print(next((str(p) for p in options if p.is_file()),'python3'))
'@
$runtimeCommand = (& wsl.exe @distributionArgs --cd $linuxProject --exec python3 -c $runtimeScript).Trim()
if ($LASTEXITCODE -ne 0 -or -not $runtimeCommand) { throw 'WSL Python runtime unavailable.' }
& wsl.exe @distributionArgs --cd $linuxProject --exec $runtimeCommand -B tools/start_photonguard.py @ForwardArguments
exit $LASTEXITCODE
