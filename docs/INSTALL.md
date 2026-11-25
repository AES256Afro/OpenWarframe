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
2. installs the latest OpenWarframe release with `uv tool install`, on Python 3.12 and with the
   exact dependency versions that release was built and tested with (its `constraints.txt`),
3. puts an **OpenWarframe** shortcut on your desktop.

If it can't find the latest release (no internet, or GitHub is down), it stops with a message
rather than installing anything else.

Then double-click **OpenWarframe** on the desktop. The first start downloads the game database
(about a minute) and shows a welcome screen. With Warframe running, click **Find my account in the
game**, or type your account ID there (the screen explains how to find it).

Prefer the command line? In a new PowerShell window, `openwarframe account howto`, then
`openwarframe account set --id <your 24-character account id>`, then `openwarframe sync`.

To update later, run the install command again.
To install a specific version, set `$env:OPENWARFRAME_REF = "v0.4.1"` first. Releases from
0.4.1 on also attach `install.ps1` itself, so
`irm https://github.com/AES256Afro/OpenWarframe/releases/latest/download/install.ps1 | iex`
runs the installer exactly as it shipped with the latest release.

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
   The first start downloads the game database (about a minute), then a welcome screen helps you
   connect your account. To keep the app on your taskbar, right-click its taskbar button and pick
   **Pin to taskbar**.
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

# Installing OpenWarframe on macOS

The Mac app is the same program in a native window (WebKit, built into macOS). It needs macOS 11
or newer; the release build is for Apple Silicon Macs.

1. From the [latest release](https://github.com/AES256Afro/OpenWarframe/releases/latest), download
   `OpenWarframe-<version>-macos.zip` and `SHA256SUMS-macos.txt`.
2. Optional: in Terminal, `cd ~/Downloads && shasum -a 256 -c SHA256SUMS-macos.txt` should print
   `OK`.
3. Unzip it and drag **OpenWarframe.app** into **Applications**.
4. The app is not notarized by Apple, so the first open is blocked. Open it once, then go to
   **System Settings > Privacy & Security**, scroll down and click **Open Anyway**. (Or in Terminal:
   `xattr -dr com.apple.quarantine /Applications/OpenWarframe.app`.) macOS only asks once.
5. The first start downloads the game database (about a minute), then shows the welcome screen.
   Type your account ID there (the screen explains how to find it).

Or run it from source with [uv](https://docs.astral.sh/uv/): `uv sync --all-groups`, then
`uv run openwarframe gui`.

The command-line tool is inside the app: `/Applications/OpenWarframe.app/Contents/MacOS/openwarframe-cli`.
Your data lives in `~/Library/Application Support/OpenWarframe`. To uninstall, delete the app and
that folder.

### What is different on a Mac

- **Get inventory from game** is Windows only. macOS does not let one app read another app's
  memory. Load your inventory with **Load inventory file** instead; everything else works the same.
- **Reward helper** reads the reward names with Apple's own text recognition (Vision). The first
  time it runs, macOS asks for **Screen Recording** permission for OpenWarframe; allow it in
  **System Settings > Privacy & Security > Screen Recording**, then restart the app.
- **Mission tracking and the reward helper** read Warframe's `EE.log`. OpenWarframe looks for it
  in the native Mac client's folders and in CrossOver, Whisky and Wine bottles, and uses the one
  the game wrote to last. If it picks the wrong one, start the app with
  `OPENWARFRAME_WARFRAME_DIR=/path/to/folder/with/EE.log`.
