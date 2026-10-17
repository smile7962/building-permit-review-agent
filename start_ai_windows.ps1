# Only use the official OpenAI API endpoint. No API key is written to disk.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:AI_MODE = 'on'
$env:AI_BASE_URL = 'https://api.openai.com/v1'
$chosenModel = Read-Host 'API model (Enter = gpt-4.1-mini)'
$env:AI_MODEL = if ([string]::IsNullOrWhiteSpace($chosenModel)) { 'gpt-4.1-mini' } else { $chosenModel.Trim() }
Write-Host 'OpenAI API key (input hidden, do not paste into chat or files):'
$secureKey = Read-Host 'API key' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
  $env:AI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ([string]::IsNullOrWhiteSpace($env:AI_API_KEY)) {
  Write-Host 'API key is empty. AI mode not started.'
  Remove-Item Env:AI_API_KEY -ErrorAction SilentlyContinue
  exit 1
}
try {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 server.py
  } else {
    & python server.py
  }
} finally {
  Remove-Item Env:AI_API_KEY -ErrorAction SilentlyContinue
  Remove-Item Env:AI_MODE -ErrorAction SilentlyContinue
  Remove-Item Env:AI_MODEL -ErrorAction SilentlyContinue
  Remove-Item Env:AI_BASE_URL -ErrorAction SilentlyContinue
}
