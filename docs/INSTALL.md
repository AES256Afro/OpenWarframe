# Installing OpenWarframe on Windows

There are three ways in. All are free, need no admin rights and leave Warframe untouched.

| | Setup (recommended) | PowerShell script | Standalone zip |
| --- | --- | --- | --- |
| Download | `OpenWarframe-<version>-windows-setup.exe` | One line in PowerShell | `OpenWarframe-<version>-windows.zip` |
| Gets you | Start menu entry, optional desktop icon, uninstaller in Settings | `openwarframe` command, desktop icon | `OpenWarframe.exe` and `openwarframe-cli.exe` in a folder |
| Installs to | `%LOCALAPPDATA%\Programs\OpenWarframe` | uv's tool folder | Wherever you unzip it |
| Updating | Run the newer setup; it replaces the old version | Run the same line again | Download the new zip |
| Windows warnings | SmartScreen once, possibly antivirus (see below) | None | SmartScreen once, possibly antivirus |

Pick one. Using two gives you two copies of the program; they share the same data folder,
`%LOCALAPPDATA%\OpenWarframe`.

## Option 1: Setup (recommended)

1. Go to the [latest release](https://github.com/AES256Afro/OpenWarframe/releases/latest) and
   download `OpenWarframe-<version>-windows-setup.exe` (and `SHA256SUMS.txt` if you want to
   [check the download](#checking-the-download)).
2. Double-click it. Because it is not code-signed yet, Windows SmartScreen may say "Windows
   protected your PC": click **More info**, then **Run anyway**
   ([why](#why-the-warnings-and-is-it-safe)).
3. Click through: tick **Create a desktop shortcut** if you want one, then **Install**. There is no
   folder to choose and no admin prompt; it installs for your Windows user only, into
   `%LOCALAPPDATA%\Programs\OpenWarframe`.
4. OpenWarframe is now in the Start menu. The first start downloads the game database (about a
   minute), then a welcome screen helps you connect your account. To keep it on your taskbar,
   right-click its taskbar button and pick **Pin to taskbar**.

**Updating:** download the newer setup and run it. It closes OpenWarframe if it is running and
replaces the old version in place; your Start menu entry, shortcuts and data stay.

**Uninstalling:** **Settings > Apps > Installed apps**, find **OpenWarframe**, **Uninstall**. This
removes the program and its shortcuts. Your data (`%LOCALAPPDATA%\OpenWarframe`: goals,
settings, snapshots, logs) is kept, so a reinstall picks up where you left off; delete that
folder yourself if you want it gone.

**Command line:** the CLI is installed as
`%LOCALAPPDATA%\Programs\OpenWarframe\openwarframe-cli.exe` (not on PATH). For example, in
PowerShell: `& "$env:LOCALAPPDATA\Programs\OpenWarframe\openwarframe-cli.exe" sync`. If you live
on the command line, option 2 gives you a plain `openwarframe` command instead.

**Silent install** (for scripts): `OpenWarframe-<version>-windows-setup.exe /VERYSILENT` installs
without questions; add `/TASKS=desktopicon` for the desktop shortcut. Uninstall silently with
`"%LOCALAPPDATA%\Programs\OpenWarframe\unins000.exe" /VERYSILENT`.

## Option 2: PowerShell script

For people who like the command line. It installs from the published source, so there is no
prebuilt `.exe` for SmartScreen or antivirus to judge. Open PowerShell (Start menu, type
`powershell`) and paste:

```powershell
irm https://github.com/AES256Afro/OpenWarframe/releases/latest/download/install.ps1 | iex
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
To install a specific version, set `$env:OPENWARFRAME_REF = "v0.4.1"` first.

The command above runs the copy of `install.ps1` attached to the latest release, so it only
changes when a new version ships. The copy in the repository
(`https://raw.githubusercontent.com/AES256Afro/OpenWarframe/main/packaging/install.ps1`) still
works, but follows `main` as it changes.

To uninstall: `uv tool uninstall openwarframe` and delete the desktop shortcut. Your data lives in
`%LOCALAPPDATA%\OpenWarframe`; delete that folder too if you want it gone.

## Option 3: standalone zip (no install)

For a portable copy, for example on a USB stick or in a folder you choose.

1. Go to the [latest release](https://github.com/AES256Afro/OpenWarframe/releases/latest) and download
   `OpenWarframe-<version>-windows.zip` (and `SHA256SUMS.txt` to
   [check the download](#checking-the-download)).
2. Right-click the zip, **Extract All**, and open the `OpenWarframe` folder.
3. Double-click **OpenWarframe.exe**. Because the app is not code-signed, Windows SmartScreen may say
   "Windows protected your PC". Click **More info**, then **Run anyway**. You only need to do this once.
   The first start downloads the game database (about a minute), then a welcome screen helps you
   connect your account. To keep the app on your taskbar, right-click its taskbar button and pick
   **Pin to taskbar**.
4. For command-line use, run `openwarframe-cli.exe` from that folder in PowerShell, for example
   `.\openwarframe-cli.exe codex update` and `.\openwarframe-cli.exe sync`. It is the same program as
   the `openwarframe` command in option 2. (It has a different name because Windows file names
   ignore case, so `openwarframe.exe` would clash with `OpenWarframe.exe`.)

Keep the whole folder together; the `.exe` files need the `_internal` folder next to them. To make a
desktop icon, right-click `OpenWarframe.exe`, **Send to**, **Desktop (create shortcut)**.

To uninstall, delete the folder (and `%LOCALAPPDATA%\OpenWarframe` if you want your data gone).

## Updating

From version 0.10.0, the app updates itself. When a new version is out, the sidebar shows
**Update to x.y.z now**. Click it and OpenWarframe:

1. downloads the same kind of file you installed from (the Setup .exe, the Windows zip or the
   macOS zip) into its data folder's `updates` folder;
2. checks it against the release's `SHA256SUMS` list and stops if it doesn't match;
3. closes, installs it and opens the new version:
   - **Setup:** the new setup runs on its own with a progress window. It installs per user, so
     there is no admin prompt, and your Start menu entry stays the same.
   - **Zip:** a small PowerShell window swaps the files in the folder you unpacked the zip to.
   - **macOS:** the app bundle is replaced where it is (usually Applications).

Your data folder (goals, settings, snapshots) is never touched. The PowerShell-script install
(Option 2) runs from source, so it isn't updated from the app: run the install command again.
Turn off the daily check in Settings if you'd rather not be told about new versions.

## Checking the download

Optional but recommended for the setup and the zip. In PowerShell, in your Downloads folder
(with the name of the file you downloaded):

```powershell
Get-FileHash .\OpenWarframe-v0.7.0-windows-setup.exe -Algorithm SHA256
```

Compare the hash with the matching line in `SHA256SUMS.txt` (case does not matter). If they
differ, do not run it: the file is damaged or not the one we published.

## Why the warnings, and is it safe?

OpenWarframe is open source (MIT) and the setup and the zip are built by GitHub Actions from the
tagged source, in public, by [.github/workflows/release.yml](../.github/workflows/release.yml).
They are **not code-signed** yet: a signing certificate costs money every year, and the project
does not have one. That is why:

- **SmartScreen** warns about any unsigned download it has not seen many times before. "More info,
  Run anyway" is the expected step.
- **Antivirus false positives** can happen. The app is built with PyInstaller, which many other
  programs (including some malware) also use, so some antivirus engines flag PyInstaller builds in
  general. (It ships as a folder of files rather than one self-extracting `.exe`, which would
  start slower and be flagged more often.) OpenWarframe also reads the running Warframe process's memory, read-only, when you click
  **Get inventory from game**, which some engines treat as suspicious. If your antivirus blocks or
  quarantines the app, you can:
  - [verify the checksum](#checking-the-download), then add an exception for the OpenWarframe
    program folder (`%LOCALAPPDATA%\Programs\OpenWarframe` for the setup), or
  - use option 2 instead, which runs from the published source with no prebuilt `.exe`, or
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

## Troubleshooting

- **The log.** OpenWarframe writes what it does to `logs/openwarframe.log` in your data folder
  (`%LOCALAPPDATA%\OpenWarframe\logs` on Windows, `~/Library/Application Support/OpenWarframe/logs`
  on macOS), errors included. The game session key is masked in it. Attach it to a bug report,
  after looking it over.
- **Check the install.** `openwarframe selfcheck` confirms the files that ship with the app
  are present.
- **Back up before reinstalling.** `openwarframe backup` writes your goals, settings, profile
  history and inventory to one zip in `backups/`. To restore, close OpenWarframe and unzip it
  into the data folder. The game data downloads again by itself.
