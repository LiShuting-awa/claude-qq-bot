$ErrorActionPreference = "SilentlyContinue"

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -and $_.CommandLine -match 'bot\.py' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
        Write-Host "已停止 Bot 进程 $($_.ProcessId)"
    }

Get-Process NapCatWinBootMain | Stop-Process -Force
Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" |
    Where-Object { $_.ExecutablePath -like "*NapCat.52230.Shell*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
        Write-Host "已停止 NapCat QQ 进程 $($_.ProcessId)"
    }

Write-Host "已停止 Bot 与 NapCat（不影响系统里其他 QQ 客户端）。"
