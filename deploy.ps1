$ErrorActionPreference = 'Stop'

# Build the payload and deploy everything to the phone via ADB.
# Usage: powershell -ExecutionPolicy Bypass -File .\deploy.ps1

Set-Location -LiteralPath $PSScriptRoot

$destination = '/data/local/tmp/civswitch'
$termuxHome = '/data/data/com.termux/files/home'
$termuxPython = '/data/data/com.termux/files/usr/bin/python3'

foreach ($tool in @('adb', 'node', 'npm')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "ERROR: $tool not found. Install ADB, Node.js and npm on the PC."
    }
}

& adb get-state *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'ERROR: Connect exactly one phone via USB, enable USB debugging and accept authorization.'
}

Write-Host 'Checking Termux and root access (allow root on the phone if prompted)...'
& adb shell "su -c '[ -d $termuxHome ]'"
if ($LASTEXITCODE -ne 0) {
    throw 'ERROR: Open Termux on the phone and grant root access before deploying.'
}
& adb shell "su -c '[ -x $termuxPython ]'"
if ($LASTEXITCODE -ne 0) {
    throw 'ERROR: Python not found. In Termux, outside the root shell, run: pkg install python'
}

Write-Host 'Building payload...'
Push-Location (Join-Path $PSScriptRoot 'PicoSwitch')
try {
    & npm install --silent
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
    & node compress.js
    if ($LASTEXITCODE -ne 0) { throw 'Payload generation failed.' }
} finally {
    Pop-Location
}

$payload = Join-Path $PSScriptRoot 'PicoSwitch/payload.txt'
if (-not (Test-Path -LiteralPath $payload)) { throw 'ERROR: Failed to generate payload.txt.' }
$lineCount = @(Get-Content -LiteralPath $payload).Count
Write-Host "Payload ready ($lineCount lines)"

Write-Host 'Pushing scripts to phone...'
& adb shell mkdir -p $destination
if ($LASTEXITCODE -ne 0) { throw 'Could not create the destination folder on the phone.' }
foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'AndroidSwitch') -File | Where-Object { $_.Extension -in '.sh', '.py' })) {
    & adb push $file.FullName "$destination/"
    if ($LASTEXITCODE -ne 0) { throw "Failed to push $($file.Name)." }
}
& adb push $payload "$destination/payload.txt"
if ($LASTEXITCODE -ne 0) { throw 'Failed to push payload.txt.' }

Write-Host 'Creating shortcuts in Termux home...'
foreach ($script in @('teardown.sh', 'test.sh', 'run.sh')) {
    & adb shell "su -c 'ln -sf $destination/$script $termuxHome/$script'"
    if ($LASTEXITCODE -ne 0) { throw "Failed to create $script shortcut." }
}
& adb shell "su -c 'ln -sfn $destination $termuxHome/civswitch'"
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the civswitch shortcut.' }

Write-Host ''
Write-Host '========================================'
Write-Host '  DEPLOY COMPLETE'
Write-Host '========================================'
Write-Host ''
Write-Host '>>> Unplug the phone from the PC. <<<'
Write-Host ''
Write-Host 'On the phone, open Termux and type:'
Write-Host '  su'
Write-Host '  setenforce 0'
Write-Host '  sh test.sh        # Type two test messages'
Write-Host '  sh run.sh         # Run the full procedure after the test succeeds'
Write-Host ''
Write-Host 'Run one command at a time, with the phone unplugged.'
Write-Host 'Connect it to the Switch dock when prompted. Normal USB is restored automatically.'
Write-Host 'Recovery: sh teardown.sh'
