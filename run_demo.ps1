$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$venvStreamlit = Join-Path $repoRoot 'venv_short\Scripts\streamlit.exe'

if (-not (Test-Path $venvStreamlit)) {
    Write-Host 'venv_short was not found. Create the short-path environment before the demo.' -ForegroundColor Red
    Write-Host 'Expected command:' -ForegroundColor Yellow
    Write-Host '  python -m venv venv_short' -ForegroundColor Yellow
    Write-Host '  .\venv_short\Scripts\python.exe -m pip install numpy tensorflow streamlit pyserial shap pandas plotly scipy groq python-dotenv scikit-learn --only-binary :all:' -ForegroundColor Yellow
    exit 1
}

$env:TF_CPP_MIN_LOG_LEVEL = '2'
$env:PYTHONUTF8 = '1'

Write-Host 'Starting ANS dashboard in demo-safe mode...' -ForegroundColor Cyan
Write-Host 'Use Ctrl+C to stop the app.' -ForegroundColor Cyan

& $venvStreamlit run app.py --server.headless true --server.port 8511