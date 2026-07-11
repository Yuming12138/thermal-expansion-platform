$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$env:PYTHONPATH = Join-Path $ProjectRoot 'src'

& python -m te_platform @args
exit $LASTEXITCODE
