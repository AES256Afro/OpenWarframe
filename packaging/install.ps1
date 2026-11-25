# OpenWarframe installer for Windows.
#
#   irm https://github.com/AES256Afro/OpenWarframe/releases/latest/download/install.ps1 | iex
#
# What it does, in order:
#   1. Installs uv (https://docs.astral.sh/uv/) with Astral's official installer if it is missing.
#   2. Installs the latest OpenWarframe release as a uv tool, on Python 3.12, with the exact
#      dependency versions that release was tested with (its constraints.txt).
#   3. Puts an OpenWarframe shortcut on your desktop.
# Nothing needs admin rights. Set $env:OPENWARFRAME_REF to a tag (or a branch, for testing)
# to install something else.

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
function Get-LatestTag {
    try {
        return (Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing).tag_name
    } catch { }
    # the API allows 60 anonymous calls an hour; the releases/latest page redirects to the tag
    try {
        $r = Invoke-WebRequest "https://github.com/$Repo/releases/latest" -UseBasicParsing -Method Head
        $uri = if ($r.BaseResponse.ResponseUri) { $r.BaseResponse.ResponseUri } else { $r.BaseResponse.RequestMessage.RequestUri }
        if ("$uri" -match '/releases/tag/([^/?#]+)') { return $Matches[1] }
    } catch { }
    return $null
}

$ref = $env:OPENWARFRAME_REF
if (-not $ref) {
    $ref = Get-LatestTag
    if (-not $ref) {
        throw "Could not look up the latest OpenWarframe release. Check your internet connection and run this again."
    }
}
$isTag = $ref -match '^v\d'

if (Get-Command git -ErrorAction SilentlyContinue) {
    $source = "git+https://github.com/$Repo@$ref"
} else {
    # uv needs git for git+ URLs; a source archive works without it.
    $kind = if ($isTag) { 'tags' } else { 'heads' }
    $source = "https://github.com/$Repo/archive/refs/$kind/$ref.zip"
}

# Exact versions this release was built and tested with, so a new release of some
# dependency can't change what gets installed.
$installArgs = @('tool', 'install', '--force', '--python', '3.12')
if ($isTag) {
    $constraints = Join-Path ([IO.Path]::GetTempPath()) "openwarframe-$ref-constraints.txt"
    try {
        Invoke-WebRequest "https://github.com/$Repo/releases/download/$ref/constraints.txt" -UseBasicParsing -OutFile $constraints
        $installArgs += @('--constraints', $constraints)
    } catch {
        Write-Host "Release $ref has no constraints.txt (releases before 0.4.1); dependency versions are not pinned." -ForegroundColor Yellow
    }
} else {
    Write-Host "Installing branch ${ref}: dependency versions are not pinned." -ForegroundColor Yellow
}

Write-Step "Installing OpenWarframe $ref"
uv @installArgs $source
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
