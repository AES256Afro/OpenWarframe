# OpenWarframe installer for Windows.
#
#   irm https://raw.githubusercontent.com/AES256Afro/OpenWarframe/main/packaging/install.ps1 | iex
#
# What it does, in order:
#   1. Installs uv (https://docs.astral.sh/uv/) with Astral's official installer if it is missing.
#   2. Installs the latest tagged OpenWarframe release as a uv tool (uv fetches Python itself).
#   3. Puts an OpenWarframe shortcut on your desktop.
# Nothing needs admin rights. Set $env:OPENWARFRAME_REF to a tag or branch to install something else.

$ErrorActionPreference = 'Stop'
$Repo = 'AES256Afro/OpenWarframe'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $extra = Join-Path $HOME '.local\bin'
    $env:Path = (@($extra, $user, $machine) | Where-Object { $_ }) -join ';'
}

# 1. uv
Update-SessionPath
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Step 'Installing uv (official installer from astral.sh)'
    powershell -NoProfile -ExecutionPolicy ByPass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
    Update-SessionPath
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv was installed but is not on PATH. Open a new PowerShell window and run this again.'
    }
} else {
    Write-Step "uv found: $((Get-Command uv).Source)"
}

# 2. OpenWarframe
$ref = $env:OPENWARFRAME_REF
if (-not $ref) {
    try {
        $ref = (Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing).tag_name
    } catch {
        $ref = $null
    }
    if (-not $ref) {
        Write-Host 'Could not look up the latest release; installing from main.' -ForegroundColor Yellow
        $ref = 'main'
    }
}

if (Get-Command git -ErrorAction SilentlyContinue) {
    $source = "git+https://github.com/$Repo@$ref"
} else {
    # uv needs git for git+ URLs; a source archive works without it.
    $kind = if ($ref -eq 'main') { 'heads' } else { 'tags' }
    $source = "https://github.com/$Repo/archive/refs/$kind/$ref.zip"
}

Write-Step "Installing OpenWarframe $ref"
uv tool install --force $source
if ($LASTEXITCODE -ne 0) { throw "uv tool install failed (exit $LASTEXITCODE)" }
uv tool update-shell | Out-Null
Update-SessionPath

# 3. Desktop shortcut
Write-Step 'Adding the desktop shortcut'
openwarframe gui --shortcut
if ($LASTEXITCODE -ne 0) { Write-Host 'Shortcut step failed; you can run: openwarframe gui --shortcut' -ForegroundColor Yellow }

Write-Host ''
Write-Host 'OpenWarframe is installed.' -ForegroundColor Green
Write-Host 'Next steps (in a new PowerShell window):'
Write-Host '  openwarframe account howto                      # how to find your account id'
Write-Host '  openwarframe account set --id <24-char id>      # link your public profile'
Write-Host '  openwarframe codex update                       # download the item codex'
Write-Host '  openwarframe sync                               # fetch your profile'
Write-Host 'Then double-click OpenWarframe on your desktop, or run: openwarframe gui'
