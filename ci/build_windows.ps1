$ErrorActionPreference = 'Stop'
$downloads = Join-Path $PWD '.downloads'
$payload = Join-Path $PWD 'windows6-payload'
$outputDir = Join-Path $PWD 'output'
New-Item -ItemType Directory -Force $downloads,$outputDir | Out-Null
python ci/prepare_assets.py --all
if ($LASTEXITCODE -ne 0) { throw 'Upstream asset verification failed' }
Invoke-WebRequest https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip -OutFile "$downloads/python.zip"
Copy-Item "$env:RUNNER_TEMP/ffmpeg.zip" "$downloads/ffmpeg.zip"
Copy-Item licenses/LGPL-3.0.txt "$downloads/LGPL.txt"
python -m pip download --only-binary=:all: --dest "$downloads/next-wheels" -r requirements-windows.txt
if ($LASTEXITCODE -ne 0) { throw 'Windows wheels download failed' }
python packaging/assemble.py $downloads $payload
if ($LASTEXITCODE -ne 0) { throw 'Payload assembly failed' }
choco install nsis --version=3.11 -y --no-progress
if ($LASTEXITCODE -ne 0) { throw 'NSIS installation failed' }
$nsis = "${env:ProgramFiles(x86)}/NSIS/makensis.exe"
if (!(Test-Path $nsis)) { throw 'NSIS compiler not found' }
$setup = Join-Path $outputDir 'KADRGO-Studio-6.0.1-Windows-CI-Setup.exe'
& $nsis "/DWINDOWS_BUILD" "/DPAYLOAD=$payload" "/DOUTPUT=$setup" packaging/windows.nsi
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
Get-FileHash $setup -Algorithm SHA256 | Format-List | Out-File "$setup.sha256.txt"
$installed = Start-Process $setup -ArgumentList '/S' -Wait -PassThru
if ($installed.ExitCode -ne 0) { throw 'Silent installation failed' }
$appDir = Join-Path $env:LOCALAPPDATA 'Programs/KADRGO Studio 6 Alpha'
$env:KADRGO_INSTALLED_ROOT = $appDir
# Drop the external FFmpeg bin to ensure the installed interpreter resolves its own tools.
$script = (Resolve-Path ci/installed_smoke.py).Path
& "$appDir/runtime/python.exe" $script
if ($LASTEXITCODE -ne 0) { throw 'Installed application smoke check failed' }
$vault = Join-Path $env:LOCALAPPDATA 'KADRGO Studio 6/Vault'
New-Item -ItemType Directory -Force $vault | Out-Null
$sentinel = Join-Path $vault 'uninstall-preserve-test.txt'
Set-Content $sentinel 'must survive uninstall'
Start-Process "$appDir/Uninstall.exe" -ArgumentList '/S' -Wait
if (!(Test-Path $sentinel)) { throw 'Uninstall removed user data' }
if (Test-Path "$appDir/runtime/python.exe") { throw 'Uninstall left runtime behind' }
'Installer install, private runtime startup and uninstall preservation: PASS' >> $env:GITHUB_STEP_SUMMARY
