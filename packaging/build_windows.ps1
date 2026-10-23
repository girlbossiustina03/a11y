# Build the A11y Windows app folder and A11y-Windows.zip.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }

& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt -r packaging/requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed.' }
& $python -m pip install -r requirements-voice.txt
if ($LASTEXITCODE -ne 0) { Write-Host 'Voice packages unavailable; building without them.' }

& $python packaging/make_icons.py
if ($LASTEXITCODE -ne 0) { throw 'Icon build failed.' }
& $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/a11y.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

if (Test-Path dist/A11y-Windows.zip) { Remove-Item dist/A11y-Windows.zip }
Compress-Archive -Path dist/A11y -DestinationPath dist/A11y-Windows.zip
Write-Host 'Built dist/A11y and dist/A11y-Windows.zip'
