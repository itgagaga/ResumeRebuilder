param([switch]$BundleBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
} else {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
}
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot 'runtime\browsers'
# Existing Edge/Chrome is a reliable local fallback. Use -BundleBrowser for distributable offline runtimes.
& '.\.venv\Scripts\python.exe' -c "from backend.browser import browser_ready; import sys; sys.exit(0 if browser_ready() else 1)"
if ($LASTEXITCODE -ne 0 -or $BundleBrowser) {
    & '.\.venv\Scripts\python.exe' -m playwright install chromium --only-shell
    if ($LASTEXITCODE -ne 0) { throw 'Chromium 安装失败' }
}
Push-Location frontend
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }
& '.\.venv\Scripts\python.exe' scripts/check_runtime.py
if ($LASTEXITCODE -ne 0) { throw '离线运行依赖检查失败' }
Write-Host '安装完成。运行 .\start.ps1 打开本地编辑器。'
