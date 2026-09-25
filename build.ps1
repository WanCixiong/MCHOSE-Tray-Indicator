$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$venv = Join-Path $PSScriptRoot '.build-venv'
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $python)) {
  py -3 -m venv $venv
}

& $python -m pip install --disable-pip-version-check -r requirements-dev.txt
& $python -m unittest discover -s tests -v
& $python -m ruff check .
& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name MCHOSE-Battery `
  mchose_tray.py

$exe = Join-Path $PSScriptRoot 'dist\MCHOSE-Battery.exe'
if (-not (Test-Path $exe)) {
  throw 'Build failed: EXE was not created.'
}
Write-Host "Built and verified: $exe"
