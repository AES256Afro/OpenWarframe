# Build the Windows installer from an existing PyInstaller build (used by CI, the release
# workflow and local builds).
#
#   uv run pyinstaller packaging/openwarframe.spec --noconfirm
#   uv run python packaging/third_party_notices.py dist/THIRD_PARTY_LICENSES.txt
#   pwsh packaging/build_installer.ps1
#
# Uses Inno Setup 6's ISCC.exe from PATH or its usual install folders, and installs it with
# Chocolatey (when available) if it is missing. Prints the path of the setup .exe it made.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Find-Iscc {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

foreach ($need in 'dist\OpenWarframe\OpenWarframe.exe', 'dist\THIRD_PARTY_LICENSES.txt') {
    if (-not (Test-Path (Join-Path $root $need))) {
        throw "$need is missing: run the PyInstaller build and third_party_notices.py first"
    }
}

$iscc = Find-Iscc
if (-not $iscc) {
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        throw 'Inno Setup 6 is not installed. Get it from https://jrsoftware.org/isinfo.php (or: winget install JRSoftware.InnoSetup)'
    }
    Write-Host '==> Installing Inno Setup with Chocolatey'
    choco install innosetup --no-progress -y | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "choco install innosetup failed (exit $LASTEXITCODE)" }
    $iscc = Find-Iscc
    if (-not $iscc) { throw 'Inno Setup was installed but ISCC.exe was not found' }
}
Write-Host "==> $iscc"

$before = Get-Date
& $iscc /Qp (Join-Path $root 'packaging\openwarframe.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC failed (exit $LASTEXITCODE)" }

$setup = Get-ChildItem (Join-Path $root 'dist') -Filter 'OpenWarframe-v*-windows-setup.exe' |
    Where-Object { $_.LastWriteTime -ge $before } | Select-Object -First 1
if (-not $setup) { throw 'ISCC finished but no setup .exe was written to dist\' }
Write-Host "==> $($setup.FullName) ($([math]::Round($setup.Length / 1MB, 1)) MB)"
