[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $RepositoryRoot
try {
    & uv run uvicorn te_platform.api.app:app --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Web service exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
