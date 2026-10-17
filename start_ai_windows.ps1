# Gemini free-tier is the default. Optional OpenAI API remains available.
# No API key is persisted in files, the browser, or application case records.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'BuildingON AI - API Provider'
Write-Host '[1] Google Gemini (default, free-tier eligible model)'
Write-Host '[2] OpenAI (optional, may be billable)'
$choice = (Read-Host 'Select service (Enter=1)').Trim()
if ([string]::IsNullOrWhiteSpace($choice) -or $choice -eq '1') {
  $env:AI_PROVIDER = 'gemini'
  $env:AI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/openai'
  $defaultModel = 'gemini-3.1-flash-lite'
  Write-Host 'Gemini free tier has limited quota. Google may use free-tier input to improve products.'
  Write-Host 'NEVER send real case documents or personal data; only bundled synthetic TXT is allowed.'
  Write-Host 'Get your Gemini API key at https://aistudio.google.com/api-keys'
  $keyLabel = 'Gemini API key'
} elseif ($choice -eq '2') {
  $env:AI_PROVIDER = 'openai'
  $env:AI_BASE_URL = 'https://api.openai.com/v1'
  $defaultModel = 'gpt-4.1-mini'
  Write-Host 'OpenAI API requires separate access/billing; it is not included in ChatGPT plans.'
  $keyLabel = 'OpenAI API key'
} else {
  throw 'Invalid choice. Enter 1 or 2.'
}
$chosenModel = Read-Host "API model (Enter=$defaultModel)"
$env:AI_MODEL = if ([string]::IsNullOrWhiteSpace($chosenModel)) { $defaultModel } else { $chosenModel.Trim() }
Write-Host 'API key input is hidden. Never paste it into chat, GitHub or a document.'
$secureKey = Read-Host $keyLabel -AsSecureString
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
$env:AI_MODE = 'on'
try {
  Write-Host "Provider=$env:AI_PROVIDER, Model=$env:AI_MODEL"
  if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 server.py
  } else {
    & python server.py
  }
} finally {
  Remove-Item Env:AI_API_KEY -ErrorAction SilentlyContinue
  Remove-Item Env:AI_MODE -ErrorAction SilentlyContinue
  Remove-Item Env:AI_MODEL -ErrorAction SilentlyContinue
  Remove-Item Env:AI_PROVIDER -ErrorAction SilentlyContinue
  Remove-Item Env:AI_BASE_URL -ErrorAction SilentlyContinue
}
