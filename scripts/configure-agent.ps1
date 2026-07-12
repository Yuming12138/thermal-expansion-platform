[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$SecretsDirectory = Join-Path $RepositoryRoot 'var\secrets'
$SecretPath = Join-Path $SecretsDirectory 'agent-key.dpapi'

New-Item -ItemType Directory -Path $SecretsDirectory -Force | Out-Null
$SecureKey = Read-Host '请输入 AI 中转站 API 密钥（输入不会显示）' -AsSecureString
$EncryptedKey = ConvertFrom-SecureString -SecureString $SecureKey
[System.IO.File]::WriteAllText($SecretPath, $EncryptedKey, [System.Text.UTF8Encoding]::new($false))

Write-Host 'AI 密钥已使用 Windows DPAPI 加密并保存到项目 var\secrets。'
Write-Host '该密文仅能由当前 Windows 用户解密；请重启平台使配置生效。'
