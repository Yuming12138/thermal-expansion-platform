[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $ProjectRoot '.runtime'
$UvCommand = Get-Command uv -ErrorAction SilentlyContinue

if ($null -eq $UvCommand) {
    Write-Host '未找到 uv。请先安装 uv，然后重新双击 start-windows.cmd。' -ForegroundColor Yellow
    Write-Host '安装说明：https://docs.astral.sh/uv/getting-started/installation/'
    throw 'uv is required to create the portable local environment.'
}

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $RuntimeRoot 'venv'
$env:UV_CACHE_DIR = Join-Path $RuntimeRoot 'uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeRoot 'python'
$env:UV_PYTHON = '3.11'
$env:UV_MANAGED_PYTHON = '1'
$env:UV_LINK_MODE = 'copy'
$env:TEP_CATALOG_DATABASE_PATH = Join-Path $ProjectRoot 'var\releases\catalog-v1.sqlite'
$env:TEP_WORKSPACE_DATABASE_PATH = Join-Path $ProjectRoot 'var\workspace.sqlite'

Push-Location -LiteralPath $ProjectRoot
try {
    Write-Host '正在准备项目内便携运行环境……' -ForegroundColor Cyan
    & $UvCommand.Source sync --frozen --no-dev --no-install-project --python 3.11 --managed-python
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }
    Write-Host "正在启动：http://127.0.0.1:$Port/" -ForegroundColor Green
    Write-Host '关闭此窗口或按 Ctrl+C 可停止平台。'
    & $UvCommand.Source run --frozen --no-sync python -m te_platform.launcher --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "tep-web exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
