# Smoke-test the Windows installer (used by CI and the release workflow).
#
#   pwsh packaging/installer_smoke_test.ps1 dist/OpenWarframe-v1.2.3-windows-setup.exe
#
# Installs silently, checks the files, shortcuts and uninstall entry, runs the CLI, installs
# again over itself (the upgrade path), then uninstalls and checks that the user's data
# folder was left alone. It changes the current user's profile, so run it on a CI runner or
# a throwaway VM, not on a machine with a real OpenWarframe install.

param([Parameter(Mandatory = $true)][string]$Setup)

$ErrorActionPreference = 'Stop'
$Setup = (Resolve-Path $Setup).Path
if ((Split-Path -Leaf $Setup) -notmatch '^OpenWarframe-v(.+)-windows-setup\.exe$') {
    throw "Unexpected installer name: $Setup"
}
$version = $Matches[1]

$app = Join-Path $env:LOCALAPPDATA 'Programs\OpenWarframe'
$data = Join-Path $env:LOCALAPPDATA 'OpenWarframe'
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'OpenWarframe.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'OpenWarframe.lnk'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{28266E5B-24EA-4D7D-BCF3-A81F4CBA3366}_is1'
$logDir = Join-Path ([IO.Path]::GetTempPath()) 'openwarframe-installer-smoke'
New-Item -ItemType Directory -Force $logDir | Out-Null

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Check($ok, $msg) { if (-not $ok) { throw "FAILED: $msg" }; Write-Host "  ok  $msg" }

function Install($name) {
    $log = Join-Path $logDir "$name.log"
    $p = Start-Process -FilePath $Setup -Wait -PassThru -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/TASKS=desktopicon', "/LOG=`"$log`"")
    if ($p.ExitCode -ne 0) { Get-Content $log -ErrorAction SilentlyContinue | Out-Host; throw "setup exited $($p.ExitCode)" }
}

if (Test-Path $uninstallKey) { throw 'OpenWarframe is already installed for this user; run this on a clean machine' }

# stands in for the user's goals, settings and snapshots
New-Item -ItemType Directory -Force $data | Out-Null
$marker = Join-Path $data 'installer-smoke-marker.txt'
Set-Content $marker 'keep me'

Step "Install $version"
Install 'install'
foreach ($f in 'OpenWarframe.exe', 'openwarframe-cli.exe', '_internal', 'unins000.exe', 'LICENSE.txt',
    'INSTALL.md', 'THIRD_PARTY_LICENSES.txt') {
    Check (Test-Path (Join-Path $app $f)) "$app\$f"
}
Check (Test-Path $startMenu) "Start menu shortcut $startMenu"
Check (Test-Path $desktop) "desktop shortcut $desktop"
$entry = Get-ItemProperty $uninstallKey
Check ($entry.DisplayVersion -eq $version) "uninstall entry version $($entry.DisplayVersion)"
Check ($entry.DisplayName -eq 'OpenWarframe') "uninstall entry name $($entry.DisplayName)"

$out = & (Join-Path $app 'openwarframe-cli.exe') version
Check ($LASTEXITCODE -eq 0 -and "$out" -match "openwarframe $([regex]::Escape($version))\b") "openwarframe-cli version: $out"

Step 'Install again over the existing copy (upgrade path)'
$stale = Join-Path $app '_internal\stale-from-an-older-version.txt'
Set-Content $stale 'old'
Install 'upgrade'
Check (-not (Test-Path $stale)) 'old _internal files are cleared'
Check (Test-Path (Join-Path $app 'OpenWarframe.exe')) 'app still installed'
Check (-not (Test-Path (Join-Path $app 'unins001.exe'))) 'one uninstaller, not a second install'

Step 'Uninstall'
Start-Process -FilePath (Join-Path $app 'unins000.exe') -Wait -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
# the uninstaller re-launches itself from %TEMP% and returns at once, so wait for it
$deadline = (Get-Date).AddSeconds(120)
while (((Test-Path $uninstallKey) -or (Test-Path (Join-Path $app 'OpenWarframe.exe'))) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
}
Check (-not (Test-Path $uninstallKey)) 'uninstall entry removed'
Check (-not (Test-Path (Join-Path $app 'OpenWarframe.exe'))) 'program files removed'
Check (-not (Test-Path $startMenu)) 'Start menu shortcut removed'
Check (-not (Test-Path $desktop)) 'desktop shortcut removed'
Check ((Get-Content $marker -ErrorAction SilentlyContinue) -eq 'keep me') "data folder $data kept"
Remove-Item $marker

Write-Host 'Installer smoke test passed.' -ForegroundColor Green
