; Inno Setup script for the Windows installer (OpenWarframe-v<version>-windows-setup.exe).
;
; It wraps the PyInstaller one-folder build, so build that first:
;
;   uv run pyinstaller packaging/openwarframe.spec --noconfirm
;   uv run python packaging/third_party_notices.py dist/THIRD_PARTY_LICENSES.txt
;   pwsh packaging/build_installer.ps1          (finds or installs Inno Setup, runs ISCC)
;
; Output: dist/OpenWarframe-v<version>-windows-setup.exe
;
; What it does:
; - installs per user into %LOCALAPPDATA%\Programs\OpenWarframe, so there is no admin prompt
;   and no folder to choose;
; - adds a Start menu entry and, if ticked, a desktop shortcut;
; - registers an uninstaller under Settings > Apps > Installed apps;
; - installs a newer version over the old one in place (same AppId), clearing the old
;   _internal folder first so files a newer build dropped do not linger;
; - when the app updates itself it runs this setup with /SILENT /RELAUNCH=1, and the setup
;   starts the new version once it has installed it.
;
; The user's data lives in %LOCALAPPDATA%\OpenWarframe (config.default_home), a different
; folder that this script never writes to, so uninstalling leaves it alone.
;
; The version is not written here: it is read from OpenWarframe.exe, whose version resource
; the PyInstaller spec fills from src/openwarframe/__init__.py (the single version source).
; Pass /DAppVersion=x.y.z to ISCC to override it.

#define AppName "OpenWarframe"
#define AppExe "OpenWarframe.exe"
#define BuildDir AddBackslash(SourcePath) + "..\dist\OpenWarframe"
#define RepoDir AddBackslash(SourcePath) + ".."

#if !FileExists(BuildDir + "\" + AppExe)
  #error dist\OpenWarframe\OpenWarframe.exe is missing: run the PyInstaller build first
#endif

#ifndef AppVersion
  #define AppVersion GetStringFileInfo(BuildDir + "\" + AppExe, "ProductVersion")
#endif
#if AppVersion == ""
  #error Could not read the version from OpenWarframe.exe; pass /DAppVersion=x.y.z
#endif
; numeric a.b.c.d form for the setup file's own version resource
#define AppVersionNumbers GetVersionNumbersString(BuildDir + "\" + AppExe)

[Setup]
; Never change the AppId: Windows uses it to recognise an existing install, which is what
; makes upgrades replace the old version instead of installing a second copy.
AppId={{28266E5B-24EA-4D7D-BCF3-A81F4CBA3366}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=OpenWarframe contributors
AppPublisherURL=https://github.com/AES256Afro/OpenWarframe
AppSupportURL=https://github.com/AES256Afro/OpenWarframe/issues
AppUpdatesURL=https://github.com/AES256Afro/OpenWarframe/releases
AppCopyright=MIT License
VersionInfoVersion={#AppVersionNumbers}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

; per-user install: {autopf} is %LOCALAPPDATA%\Programs in this mode
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=no

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

SetupIconFile={#RepoDir}\src\openwarframe\app\static\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
; close a running OpenWarframe (it holds its files open) before upgrading or uninstalling
CloseApplications=yes
RestartApplications=no

OutputDir={#RepoDir}\dist
OutputBaseFilename=OpenWarframe-v{#AppVersion}-windows-setup
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; an upgrade starts from a clean runtime folder
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoDir}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "{#RepoDir}\docs\INSTALL.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoDir}\dist\THIRD_PARTY_LICENSES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; the app's own "Update now" runs this setup with /SILENT /RELAUNCH=1: reopen the app when done
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Flags: nowait; Check: WantRelaunch

[Code]
function WantRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;
