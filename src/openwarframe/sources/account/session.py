"""Read the live game session and download the full inventory (Windows only, opt-in).

The game keeps its session key in memory as part of request URLs of the form
``?accountId=<24 hex>&nonce=<digits>``. This module opens the Warframe process with
read-only access (PROCESS_VM_READ), scans its private memory for that pattern, and uses
the session key to request ``inventory.php``, the same call the game makes.

It never writes to the process, never injects code, never touches game files, and never
stores the nonce: it is used for one request and discarded.

Digital Extremes' EULA names software that reads the game's memory, and their policy is
that third-party tools are used at your own risk. The CLI and the app show that warning
and require an explicit "yes" before the first use.
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass

import httpx

from ...config import USER_AGENT

PROCESS_NAMES = ("Warframe.x64.exe",)
# macOS does not let one app read another's memory without root and a disabled SIP, so the
# Mac app loads the inventory from a file instead.
SUPPORTED = sys.platform == "win32"
UNSUPPORTED_TEXT = (
    "Reading the inventory from the running game only works on Windows. On a Mac, use "
    "Load inventory file instead; everything else in the app works without it."
)
INVENTORY_HOSTS = ("https://mobile.warframe.com", "https://api.warframe.com")
SESSION_RE = re.compile(rb"\?accountId=([0-9a-f]{24})&nonce=(\d{4,24})")
MARKER = b"?accountId="

RISK_TEXT = (
    "OpenWarframe will read the running game's memory (read-only) to find your session key, "
    "then download your inventory from Digital Extremes with it. Nothing is changed in the game, "
    "and the key is never saved. Digital Extremes' EULA names software that reads game memory, "
    "and their policy is that third-party tools are used at your own risk."
)


class SessionError(RuntimeError):
    """Readable failure shown to the player."""


@dataclass
class Session:
    account_id: str
    nonce: str
    hits: int


# -- pattern search (pure, testable) -------------------------------------------------------


def find_sessions(buf: bytes) -> Counter:
    """Count (accountId, nonce) pairs in a block of memory."""
    found: Counter = Counter()
    start = 0
    while True:
        i = buf.find(MARKER, start)
        if i < 0:
            return found
        m = SESSION_RE.match(buf, i)
        if m:
            found[(m.group(1).decode(), m.group(2).decode())] += 1
        start = i + len(MARKER)


def pick_session(found: Counter, expected_account: str | None = None) -> Session | None:
    if not found:
        return None
    ranked = found.most_common()
    if expected_account:
        mine = [kv for kv in ranked if kv[0][0] == expected_account]
        if mine:
            ranked = mine
    (account_id, nonce), hits = ranked[0]
    return Session(account_id=account_id, nonce=nonce, hits=hits)


# -- Windows process access ---------------------------------------------------------------


def find_game_pid() -> int | None:
    if sys.platform != "win32":
        return None
    for name in PROCESS_NAMES:
        out = subprocess.run(  # noqa: S603, S607
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1 and parts[0].lower() == name.lower() and parts[1].isdigit():
                return int(parts[1])
    return None


def scan_process(
    pid: int, *, expected_account: str | None = None, max_region: int = 512 << 20
) -> Session | None:
    """Read-only scan of a process's committed private memory for the session pattern."""
    if sys.platform != "win32":
        raise SessionError("Reading the game session only works on Windows.")
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # noqa: N806
    PROCESS_VM_READ = 0x0010  # noqa: N806
    MEM_COMMIT, MEM_PRIVATE = 0x1000, 0x20000  # noqa: N806
    READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}  # noqa: N806
    PAGE_GUARD = 0x100  # noqa: N806

    class MBI(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wintypes.DWORD),
            ("PartitionId", wintypes.WORD),
            ("RegionSize", ctypes.c_size_t),
            ("State", wintypes.DWORD),
            ("Protect", wintypes.DWORD),
            ("Type", wintypes.DWORD),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
    k32.ReadProcessMemory.restype = wintypes.BOOL
    k32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise SessionError(
            f"Windows refused read access to the game (error {ctypes.get_last_error()}). "
            "If Warframe runs as administrator, run OpenWarframe the same way."
        )
    found: Counter = Counter()
    try:
        addr = 0
        mbi = MBI()
        chunk = 16 << 20
        overlap = 64
        while k32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if (
                mbi.State == MEM_COMMIT
                and mbi.Type == MEM_PRIVATE
                and (mbi.Protect & 0xFF) in READABLE
                and not mbi.Protect & PAGE_GUARD
                and size <= max_region
            ):
                off = 0
                while off < size:
                    n = min(chunk + overlap, size - off)
                    buf = ctypes.create_string_buffer(n)
                    got = ctypes.c_size_t(0)
                    if (
                        k32.ReadProcessMemory(handle, ctypes.c_void_p(base + off), buf, n, ctypes.byref(got))
                        and got.value
                    ):
                        found.update(find_sessions(buf.raw[: got.value]))
                    off += chunk
            addr = base + size
            if addr >= 0x7FFFFFFFFFFF:
                break
    finally:
        k32.CloseHandle(handle)
    return pick_session(found, expected_account)


# -- inventory download -------------------------------------------------------------------


def fetch_inventory(session: Session, client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    try:
        last = ""
        for host in INVENTORY_HOSTS:
            url = f"{host}/api/inventory.php"
            try:
                r = client.get(url, params={"accountId": session.account_id, "nonce": session.nonce})
            except httpx.HTTPError as exc:
                last = str(exc)
                continue
            if r.status_code == 200 and r.content.strip():
                try:
                    return r.json()
                except ValueError:
                    last = "the server sent something that is not JSON"
                    continue
            last = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 403, 409):
                break  # the session key was refused; another host won't help
        raise SessionError(
            f"Digital Extremes did not return your inventory ({last}). Finish loading into your "
            "Orbiter, wait a minute and try again."
        )
    finally:
        if own:
            client.close()


def grab_inventory(expected_account: str | None = None) -> dict:
    """Find the game, read its session, download the inventory. Returns the inventory JSON."""
    return grab_session(expected_account)[1]


def grab_session(expected_account: str | None = None) -> tuple[str, dict]:
    """Like grab_inventory, and also returns the account ID the game is signed in to."""
    pid = find_game_pid()
    if not pid:
        raise SessionError("Warframe is not running. Start the game, log in, then try again.")
    session = scan_process(pid, expected_account=expected_account)
    if not session:
        raise SessionError(
            "No session found in the game yet. Log in and wait until you are in your Orbiter, then try again."
        )
    if expected_account and session.account_id != expected_account:
        raise SessionError(
            "The running game is signed in to a different account than the one OpenWarframe is set up for."
        )
    return session.account_id, fetch_inventory(session)
