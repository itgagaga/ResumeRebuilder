param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe') -or -not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    throw '请先运行 .\setup.ps1 完成依赖安装和前端构建。'
}
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot 'runtime\browsers'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765' }
Write-Host 'Resume Rebuilder: http://127.0.0.1:8765  (Ctrl+C 停止服务)'
& '.\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
