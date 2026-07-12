[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$SecretsDirectory = Join-Path $RepositoryRoot 'var\secrets'
$SecretPath = Join-Path $SecretsDirectory 'agent-key.dpapi'

New-Item -ItemType Directory -Path $SecretsDirectory -Force | Out-Null
$Host.UI.RawUI.WindowTitle = 'TE Platform Agent Setup'
$SecureKey = Read-Host 'Paste the Agent API key (input is hidden), then press Enter' -AsSecureString
$EncryptedKey = ConvertFrom-SecureString -SecureString $SecureKey
[System.IO.File]::WriteAllText($SecretPath, $EncryptedKey, [System.Text.UTF8Encoding]::new($false))

Write-Host 'Agent API key saved with Windows DPAPI encryption in var\secrets.'
Write-Host 'The encrypted value is usable only by this Windows user.'
Write-Host 'You can close this window and tell Codex that setup is complete.'
