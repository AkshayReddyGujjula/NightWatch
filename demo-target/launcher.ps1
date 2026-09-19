param([ValidateSet('demo','cyber','reset')][string]$Action)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$health = 'http://127.0.0.1:8765/api/state'
try { Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 1 | Out-Null } catch {
  Start-Process -FilePath 'uv' -ArgumentList @('run','python','demo-target/server.py') -WorkingDirectory $repo -WindowStyle Hidden
  for ($i=0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 300
    try { Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 1 | Out-Null; break } catch {}
  }
}
$endpoint = if ($Action -eq 'reset') { 'reset' } else { "arm/$Action" }
$result = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/api/$endpoint" -TimeoutSec 45
$chrome = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $chrome) { throw 'Google Chrome was not found.' }
if (($Action -eq 'demo' -or $Action -eq 'reset') -and $result.checkout_url) {
  Start-Process -FilePath $chrome -ArgumentList $result.checkout_url
}
Start-Process -FilePath $chrome -ArgumentList 'http://127.0.0.1:8765/'
