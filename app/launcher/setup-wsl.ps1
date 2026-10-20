$ErrorActionPreference='Stop'
trap { Write-Host ('环境准备未完成：'+$_.Exception.Message) -ForegroundColor Yellow; exit 1 }
Write-Host '首次环境准备：安装微软 WSL 与 Ubuntu。需要联网、管理员确认，可能需要重启电脑。'
Write-Host '已安装并完成首次设置的用户，直接运行“启动工作台.bat”。'
$answer=Read-Host '现在安装输入 Y，其他输入退出'
if($answer -notmatch '^[Yy]$'){exit 0}
$code='& "$env:WINDIR\System32\wsl.exe" --install -d Ubuntu --no-launch; Write-Host "安装完成后如提示重启，请先重启。然后打开 Ubuntu 完成首次设置，再双击启动工作台。"; Read-Host "按 Enter 关闭"'
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
# This window is the interactive OS setup the user explicitly selected above.
Start-Process -FilePath (Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe') -Verb RunAs -ArgumentList @('-NoProfile','-EncodedCommand',$encoded) -Wait
