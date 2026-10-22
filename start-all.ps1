param(
    [string]$QQ = $env:QQ_ACCOUNT,
    [string]$NapCatHome = $env:NAPCAT_HOME
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$project = $PSScriptRoot
$logDir = Join-Path $project "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Test-PortOpen([int]$Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

if (-not (Test-PortOpen 3001)) {
    Write-Host "[napcat] 启动 NapCat ..." -ForegroundColor Cyan
    if (-not $NapCatHome) {
        throw "请通过 -NapCatHome 或 NAPCAT_HOME 环境变量指定 NapCat 安装目录。"
    }
    $launcher = Join-Path $NapCatHome "NapCatWinBootMain.exe"
    if (-not (Test-Path -LiteralPath $launcher)) {
        throw "找不到 NapCat 启动器：$launcher"
    }
    $startArgs = @{
        FilePath = $launcher
        WorkingDirectory = $NapCatHome
        WindowStyle = "Hidden"
        RedirectStandardOutput = Join-Path $logDir "napcat-$stamp.out.log"
        RedirectStandardError = Join-Path $logDir "napcat-$stamp.err.log"
    }
    if ($QQ) {
        $startArgs.ArgumentList = $QQ
    }
    Start-Process @startArgs | Out-Null

    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 2
        if (Test-PortOpen 3001) { break }
    }
}

if (-not (Test-PortOpen 3001)) {
    Write-Host "[warn] 3001 端口未监听：NapCat 可能还没登录，请查看 logs\napcat-*.log" -ForegroundColor Yellow
} else {
    Write-Host "[ok] NapCat WebSocket 3001 已就绪" -ForegroundColor Green
}

$botProcess = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -and $_.CommandLine -match 'bot\.py' }

if ($botProcess) {
    Write-Host "[ok] QQ Bot 已在运行 (PID $($botProcess.ProcessId -join ','))" -ForegroundColor Green
} else {
    Write-Host "[bot] 启动 QQ Bot ..." -ForegroundColor Cyan
    Start-Process -FilePath (Join-Path $project ".venv\Scripts\python.exe") `
        -ArgumentList "bot.py" `
        -WorkingDirectory $project `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "bot-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logDir "bot-$stamp.err.log") | Out-Null
    Start-Sleep -Seconds 3
    Write-Host "[ok] QQ Bot 已启动" -ForegroundColor Green
}

Write-Host ""
Write-Host "NapCat WebUI: http://127.0.0.1:6099/webui"
Write-Host "日志目录: $logDir"
