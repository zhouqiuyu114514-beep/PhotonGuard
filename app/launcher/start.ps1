param([switch]$NoBrowser,[switch]$NonInteractive,[switch]$Stop,[string]$Distribution)
$ErrorActionPreference='Stop'
trap { Write-Host ('启动未完成：'+$_.Exception.Message) -ForegroundColor Yellow; exit 1 }
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$wsl=Join-Path $env:WINDIR 'System32/wsl.exe'
if(-not (Test-Path -LiteralPath $wsl)){throw '这台电脑尚未安装 WSL，请先运行“首次准备环境.bat”，完成后再启动。'}
$raw=& $wsl --list --quiet 2>$null
$distros=@($raw | ForEach-Object { ($_ -replace "`0",'').Trim() } | Where-Object { $_ -and $_ -notmatch '^docker-' })
if($LASTEXITCODE -ne 0 -or $distros.Count -eq 0){throw '尚未发现可用的 WSL Linux。请运行“首次准备环境.bat”，按提示完成安装、重启和首次设置。'}
if($Distribution){if($Distribution -notin $distros){throw '指定的 WSL 发行版未安装。'}}
else{$Distribution=(@($distros | Where-Object {$_ -match '^Ubuntu'})+@($distros | Where-Object {$_ -match '^Debian$'}))[0]}
if(-not $Distribution){throw '请安装 Ubuntu WSL，或由熟悉环境的使用者指定兼容 Linux 发行版。'}
$linuxRoot=(& $wsl -d $Distribution --exec wslpath -a -u $root | Out-String).Trim()
if($LASTEXITCODE -ne 0 -or -not $linuxRoot.StartsWith('/')){throw 'WSL 尚未完成首次设置。请打开 Ubuntu，完成用户名设置后再试。'}
$entry=$linuxRoot+'/launcher/wsl-entry.sh'
if($Stop){& $wsl -d $Distribution --exec bash $entry stop $linuxRoot;exit $LASTEXITCODE}
function Identity($port){try{return (Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/bootstrap" -TimeoutSec 2).service_identity}catch{return $null}}
function Matches($value){return ($null -ne $value -and $value.release_id -eq 'photonguard-rc9-context-fix-20261016' -and $value.package_root -eq $linuxRoot -and $value.source_commit -eq '176976938f9a6d0603c4799339623227aae35c90')}
function Open-Ready($port){$url="http://127.0.0.1:$port/experiments";$boot=Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/bootstrap" -TimeoutSec 5;if(-not $boot.runtime.workers_enabled){throw '计算服务未启用，未按成功启动处理。'};if(-not $NoBrowser){Start-Process $url};Write-Host ('工作台已打开：'+$url);Write-Host '关闭浏览器不会删除记录。结束使用时双击“停止工作台.bat”。';[pscustomobject]@{status='READY';url=$url;workers_enabled=$true;source_commit=$boot.service_identity.source_commit}|ConvertTo-Json -Compress}
$state=Join-Path $root 'data/service.json'
if(Test-Path -LiteralPath $state){try{$saved=Get-Content -Raw -LiteralPath $state|ConvertFrom-Json;if(Matches (Identity $saved.port)){Open-Ready $saved.port;exit 0}}catch{}}
$rootHash=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($root))).Replace('-','')
$mutex=New-Object Threading.Mutex($false,('Local\PhotonGuardTrial-'+$rootHash))
if(-not $mutex.WaitOne(0)){throw '此试用包正在启动，请等待首次准备完成。'}
try{
    Write-Host '正在检查运行环境。首次需要联网准备，之后直接启动。'
    & $wsl -d $Distribution --exec bash $entry setup $linuxRoot
    if($LASTEXITCODE -ne 0){throw '运行环境准备未完成。可检查网络后再次双击启动，已有下载会复用。'}
    $port=$null
    foreach($candidate in 8766..8785){$id=Identity $candidate;if(Matches $id){Open-Ready $candidate;exit 0};$probe=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$candidate);try{$probe.Start();$port=$candidate;break}catch{}finally{$probe.Stop()}}
    if($null -eq $port){throw '试用端口被占用，请关闭自己不再使用的工作台后重试。'}
    $logs=Join-Path $root 'logs';New-Item -ItemType Directory -Path $logs -Force|Out-Null
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    # Every path is a quoted native argument, never executable shell text.
    $arguments=@('-d',$Distribution,'--exec','bash',$entry,'serve',$linuxRoot,[string]$port)
    $quoted=($arguments|ForEach-Object {if($_ -match '[\s"&|<>^]'){'"'+($_ -replace '(\\*)"','$1$1\"' -replace '(\\+)$','$1$1')+'"'}else{$_}}) -join ' '
    $process=Start-Process -FilePath $wsl -ArgumentList $quoted -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs ($stamp+'.out.log')) -RedirectStandardError (Join-Path $logs ($stamp+'.err.log'))
    for($i=0;$i -lt 90;$i++){Start-Sleep -Milliseconds 500;if(Matches (Identity $port)){Open-Ready $port;exit 0};if($process.HasExited){throw ('服务未能启动。请将 logs 文件夹中的本次日志发给制作同学：'+$stamp)}}
    throw '启动尚未完成，请查看 logs 中的本次日志；未停止其他服务。'
}finally{$mutex.ReleaseMutex();$mutex.Dispose()}
