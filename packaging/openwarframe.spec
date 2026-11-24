# PyInstaller spec: one-folder Windows build with two executables sharing one runtime.
#
#   uv run --with pyinstaller pyinstaller packaging/openwarframe.spec --noconfirm
#
# Output: dist/OpenWarframe/
#   OpenWarframe.exe      windowed desktop app (openwarframe.app:main)
#   openwarframe-cli.exe  console CLI (openwarframe.cli:app)
#   _internal/            Python runtime, openwarframe/app/static, openwarframe/kb_data
#
# The CLI cannot be called openwarframe.exe: Windows file names are case-insensitive, so it
# would collide with OpenWarframe.exe in the same folder.
# UPX stays off; packed binaries trip more antivirus heuristics.

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32 import versioninfo as vi

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller
SRC = ROOT / "src"
HERE = ROOT / "packaging"

datas = [
    (str(SRC / "openwarframe" / "app" / "static"), "openwarframe/app/static"),
    (str(ROOT / "kb"), "openwarframe/kb_data"),
]
hidden = collect_submodules("openwarframe")

VERSION = re.search(
    r'__version__ = "([^"]+)"', (SRC / "openwarframe" / "__init__.py").read_text(encoding="utf-8")
).group(1)
_nums = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3]) + (0,)
_nums = (_nums + (0, 0, 0, 0))[:4]


def version_info(original_name, description):
    strings = [
        vi.StringStruct("CompanyName", "OpenWarframe contributors"),
        vi.StringStruct("FileDescription", description),
        vi.StringStruct("FileVersion", VERSION),
        vi.StringStruct("InternalName", original_name),
        vi.StringStruct("LegalCopyright", "MIT License"),
        vi.StringStruct("OriginalFilename", original_name),
        vi.StringStruct("ProductName", "OpenWarframe"),
        vi.StringStruct("ProductVersion", VERSION),
    ]
    return vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=_nums, prodvers=_nums),
        kids=[
            vi.StringFileInfo([vi.StringTable("040904B0", strings)]),
            vi.VarFileInfo([vi.VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


def analysis(script):
    return Analysis(  # noqa: F821
        [str(HERE / script)],
        pathex=[str(SRC)],
        datas=datas,
        hiddenimports=hidden,
        excludes=["tkinter", "pytest"],
        noarchive=False,
    )


app_a = analysis("entry_app.py")
cli_a = analysis("entry_cli.py")

app_exe = EXE(  # noqa: F821
    PYZ(app_a.pure),  # noqa: F821
    app_a.scripts,
    [],
    exclude_binaries=True,
    name="OpenWarframe",
    console=False,
    upx=False,
    version=version_info("OpenWarframe.exe", "OpenWarframe desktop app"),
)
cli_exe = EXE(  # noqa: F821
    PYZ(cli_a.pure),  # noqa: F821
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name="openwarframe-cli",
    console=True,
    upx=False,
    version=version_info("openwarframe-cli.exe", "OpenWarframe command line"),
)

COLLECT(  # noqa: F821
    app_exe,
    cli_exe,
    app_a.binaries,
    app_a.datas,
    cli_a.binaries,
    cli_a.datas,
    upx=False,
    name="OpenWarframe",
)
