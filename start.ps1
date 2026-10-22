$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "[setup] 创建虚拟环境..." -ForegroundColor Cyan
    python -m venv .venv
    & $python -m pip install -r requirements.txt
}

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[setup] 已生成 .env，请填写 ANTHROPIC_API_KEY 后重新运行。" -ForegroundColor Yellow
    exit 1
}

Write-Host "[run] 启动 QQ Bot..." -ForegroundColor Green
& $python bot.py
