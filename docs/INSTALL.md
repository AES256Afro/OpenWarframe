# Installing OpenWarframe on Windows

There are two ways in. Both are free, need no admin rights and leave Warframe untouched.

| | Installer script (recommended) | Standalone zip |
| --- | --- | --- |
| Needs | PowerShell (built into Windows) | Nothing |
| Gets you | `openwarframe` command, desktop icon, easy updates | `OpenWarframe.exe` and `openwarframe-cli.exe` in a folder |
| Updating | Run the same command again | Download the new zip |
| Windows warnings | None | SmartScreen and possibly antivirus (see below) |

## Option 1: installer script (recommended)

Open PowerShell (Start menu, type `powershell`) and paste:

```powershell
irm https://raw.githubusercontent.com/AES256Afro/OpenWarframe/main/packaging/install.ps1 | iex
```

The script ([packaging/install.ps1](../packaging/install.ps1), read it first if you like):

1. installs [uv](https://docs.astral.sh/uv/) with Astral's official installer if you do not have it
   (uv also downloads the Python it needs; nothing touches a Python you already have),
2. installs the latest OpenWarframe release with `uv tool install`,
3. puts an **OpenWarframe** shortcut on your desktop.

Then, in a new PowerShell window:

```powershell
openwarframe account howto
```

```powershell
openwarframe account set --id <your 24-character account id>
```

```powershell
openwarframe codex update
```

```powershell
openwarframe sync
```

and double-click **OpenWarframe** on the desktop. To update later, run the install command again.
To install a specific version, set `$env:OPENWARFRAME_REF = "v0.3.0"` first.

To uninstall: `uv tool uninstall openwarframe` and delete the desktop shortcut. Your data lives in
`%LOCALAPPDATA%\OpenWarframe`; delete that folder too if you want it gone.

## Option 2: standalone zip (no Python, no uv)

1. Go to the [latest release](https://github.com/AES256Afro/OpenWarframe/releases/latest) and download
   `OpenWarframe-<version>-windows.zip` and `SHA256SUMS.txt`.
2. **Check the download** (optional but recommended). In PowerShell, in your Downloads folder:

   ```powershell
   (Get-FileHash .\OpenWarframe-v0.3.0-windows.zip -Algorithm SHA256).Hash
   ```

   Compare the result with the line in `SHA256SUMS.txt` (case does not matter). If they differ, do
   not run it: the file is damaged or not the one we published.
3. Right-click the zip, **Extract All**, and open the `OpenWarframe` folder.
4. Double-click **OpenWarframe.exe**. Because the app is not code-signed, Windows SmartScreen may say
   "Windows protected your PC". Click **More info**, then **Run anyway**. You only need to do this once.
5. For command-line use, run `openwarframe-cli.exe` from that folder in PowerShell, for example
   `.\openwarframe-cli.exe codex update` and `.\openwarframe-cli.exe sync`. It is the same program as
   the `openwarframe` command in option 1. (It has a different name because Windows file names
   ignore case, so `openwarframe.exe` would clash with `OpenWarframe.exe`.)

Keep the whole folder together; the `.exe` files need the `_internal` folder next to them. To make a
desktop icon, right-click `OpenWarframe.exe`, **Send to**, **Desktop (create shortcut)**.

### Why the warnings, and is it safe?

OpenWarframe is open source (MIT) and the zip is built by GitHub Actions from the tagged source, in
public, by [.github/workflows/release.yml](../.github/workflows/release.yml). It is **not code-signed**:
a signing certificate costs money every year, and the project does not have one. That is why:

- **SmartScreen** warns about any unsigned download it has not seen many times before. "More info,
  Run anyway" is the expected step.
- **Antivirus false positives** can happen. The app is built with PyInstaller, which many other
  programs (including some malware) also use, so some antivirus engines flag PyInstaller builds in
  general. OpenWarframe also reads the running Warframe process's memory, read-only, when you click
  **Get inventory from game**, which some engines treat as suspicious. If your antivirus blocks or
  quarantines the app, you can:
  - verify the checksum as above, then add an exception for the `OpenWarframe` folder, or
  - use option 1 instead, which runs from the published source with no prebuilt `.exe`, or
  - report the false positive to your antivirus vendor (Microsoft Defender:
    <https://www.microsoft.com/wdsi/filesubmission>).

Never download OpenWarframe from anywhere except the GitHub release page or the command above.
