$ErrorActionPreference = "Stop"
$Project = $PSScriptRoot
$EnvFile = Join-Path $Project ".env"
$Python = Join-Path $Project ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== Claude QQ Bot - Anthropic API Key ===" -ForegroundColor Cyan
Write-Host "Paste your API key below and press Enter (input is hidden)."
Write-Host "It will only be written to: $EnvFile"
Write-Host ""

$secure = Read-Host "ANTHROPIC_API_KEY" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim()
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if ([string]::IsNullOrWhiteSpace($key)) {
    Write-Host "No key entered. Nothing changed." -ForegroundColor Yellow
    Read-Host "Press Enter to close"
    exit 1
}

$content = [IO.File]::ReadAllText($EnvFile)
if ($content -match '(?m)^ANTHROPIC_API_KEY=.*$') {
    $replacement = "ANTHROPIC_API_KEY=$key"
    $content = [regex]::Replace($content, '(?m)^ANTHROPIC_API_KEY=.*$', { param($m) $replacement })
} else {
    $content = $content.TrimEnd() + "`r`nANTHROPIC_API_KEY=$key`r`n"
}
[IO.File]::WriteAllText($EnvFile, $content, (New-Object Text.UTF8Encoding($false)))
Write-Host "Key saved (length $($key.Length))." -ForegroundColor Green

Write-Host "Restarting QQ Bot ..." -ForegroundColor Cyan
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -and $_.CommandLine -match "bot\.py" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

$logDir = Join-Path $Project "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Start-Process -FilePath $Python `
    -ArgumentList "bot.py" `
    -WorkingDirectory $Project `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir "bot-$stamp.out.log") `
    -RedirectStandardError (Join-Path $logDir "bot-$stamp.err.log") | Out-Null
Start-Sleep -Seconds 4

Write-Host ""
Write-Host "Testing Claude API ..." -ForegroundColor Cyan
& $Python (Join-Path $Project "check_claude.py")
Write-Host ""
Read-Host "Done. Press Enter to close"
