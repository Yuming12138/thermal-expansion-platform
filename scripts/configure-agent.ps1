[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ConfigDirectory = Join-Path $RepositoryRoot 'var\config'
$ConfigPath = Join-Path $ConfigDirectory 'agent.env'

New-Item -ItemType Directory -Path $ConfigDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    $Template = @(
        'TEP_AGENT_BASE_URL=https://api.cmsg666.xyz/v1'
        'TEP_AGENT_MODEL=gpt-5.6-luna'
        'TEP_AGENT_API_KEY='
    ) -join [Environment]::NewLine
    [System.IO.File]::WriteAllText($ConfigPath, $Template, [System.Text.UTF8Encoding]::new($false))
}

$Editor = Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $ConfigPath + '"') -PassThru
Write-Host 'The local Agent configuration file is open in Notepad.'
Write-Host 'Paste the key after TEP_AGENT_API_KEY=, save the file, and close Notepad.'
Write-Host 'This plaintext file is local and excluded from Git. Do not share it.'
Wait-Process -Id $Editor.Id
