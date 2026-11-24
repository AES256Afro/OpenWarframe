"""Follow Warframe's EE.log and turn the lines we care about into typed events.

The game writes ``%LOCALAPPDATA%\\Warframe\\EE.log`` while it runs and recreates the file
at every launch. We only ever *read* it: each poll opens the file, reads what is new and
closes it again, so we never hold a handle that could get in the way of the game
deleting or truncating it.

Reward-screen lines were first taken from WFInfo (https://github.com/WFCD/WFinfo, MIT),
``WFInfo/Data.cs`` method ``LogChanged`` on master, read 2026-11-24 (blob ``6d88b42b``).
WFInfo reads the same text from the ``DBWIN_BUFFER`` debug stream instead of the file::

    if (line.Contains("Pause countdown done") || line.Contains("Got rewards"))
        -> AutoTriggered()            # start the reward scan
    if (line.Contains("MatchingService::EndSession") || line.Contains("Relic timer closed"))
        -> rewardsDisplaying = false

They were then checked against the owner's own 4-player Lith fissure (Defense, game build
2026.10.28, EE.log of 2026-11-24). The real order is::

    12815.410 Sys [Info]: VoidProjections: OpenVoidProjectionRewardScreenRMI
    12820.412 Script [Info]: ProjectionsCountdown.lua: Relic timer closed
    12820.412 Script [Info]: ProjectionRewardChoice.lua: Pause countdown done
    12820.420 Script [Info]: ProjectionRewardChoice.lua: Relic rewards initialized
    12820.587 Sys [Info]: VoidProjections: <id> gets reward /Lotus/StoreItems/Types/Recipes/...
    12820.879 Sys [Info]: VoidProjections: Client has reward info for all players now
    12820.879 Script [Info]: ProjectionRewardChoice.lua: Got rewards        <- names on screen
    12835.881 Script [Info]: ProjectionRewardChoice.lua: Selection countdown done
    12835.881 Script [Info]: ProjectionRewardChoice.lua: Relic reward screen shut down

So we differ from WFInfo on purpose: "Pause countdown done" comes before the names are
drawn, and "Relic timer closed" fires for every countdown (several times per screen), so
neither is used. The relic *selection* screen between Defense rounds also logs "Relic
rewards initialized" and "shut down" but never "Got rewards", so it is correctly ignored.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

# The reward names are on screen once this is logged (see module docstring).
REWARD_OPEN_MARKERS = ("ProjectionRewardChoice.lua: Got rewards",)
# The screen is gone; EndSession (also a WFInfo marker) covers leaving the mission early.
REWARD_CLOSE_MARKERS = ("Relic reward screen shut down", "MatchingService::EndSession")
# One player's reward, by item path, logged while the screen loads (not every player's):
#   VoidProjections: <your account id> gets reward /Lotus/StoreItems/Types/Recipes/...
GETS_REWARD_RE = re.compile(r"VoidProjections: (?P<player>\w+) gets reward (?P<item>/\S+)")
# Seen in the owner's EE.log: "11.729 Sys [Info]: Logged in <name>"
LOGIN_RE = re.compile(r"\bSys \[\w+\]: Logged in (?P<name>\S+)")
# Seen in the owner's EE.log:
#   2540.750 Sys [Info]: Client loaded {"difficulty":0,"name":"SolNode129"} with MissionInfo:
#   {                      <- pretty-printed JSON follows on the next lines
LOADED_RE = re.compile(r"Client loaded (?P<head>\{.*?\})?\s*with MissionInfo:")
# every normal log line starts with "<seconds since launch> <Category> [<Level>]:"
STAMP_RE = re.compile(r"^(?P<t>\d+\.\d+) \w+ \[\w+\]:")
# Lines worth keeping while we still tune the triggers (``openwarframe live record``).
CANDIDATE_RE = re.compile(
    r"reward|relic|projection|countdown|fissure|void|EndSession|MissionInfo|Logged in", re.IGNORECASE
)


def default_log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Warframe" / "EE.log"


@dataclass
class Event:
    kind: str  # mission_loaded | reward_screen_opened | reward_screen_closed | reward_reported | login | log_reset
    time: float | None  # seconds since game launch, from the log line
    line: str
    data: dict = field(default_factory=dict)

    def describe(self) -> str:
        t = f"{self.time:9.3f}" if self.time is not None else " " * 9
        extra = " ".join(f"{k}={v}" for k, v in self.data.items() if k != "mission_info")
        return f"{t}  {self.kind:<22} {extra}".rstrip()


# -- tailing ------------------------------------------------------------------------------


class LogTailer:
    """Return complete new lines from a log file that may be truncated or recreated.

    A file counts as new when its identity (file id + creation time) changes, it shrinks
    below our read position, or its first bytes change. Then we start again from the top
    and ``poll`` reports it through ``reset``.
    """

    HEAD = 64

    def __init__(self, path: Path, *, from_start: bool = False, encoding: str = "utf-8"):
        self.path = Path(path)
        self.encoding = encoding
        self.pos = 0
        self._partial = b""
        self._ident: tuple | None = None
        self._head = b""
        self.resets = 0
        self.reset = False  # set by poll() when the file was replaced since the last poll
        if not from_start:
            self._skip_to_end()

    def _identity(self, st: os.stat_result) -> tuple:
        return (st.st_ino, getattr(st, "st_birthtime", st.st_ctime))

    def _skip_to_end(self) -> None:
        try:
            st = self.path.stat()
        except OSError:
            return
        self._ident = self._identity(st)
        self.pos = st.st_size
        self._head = self._read_head()
        # never start inside a line
        if self.pos:
            with self.path.open("rb") as f:
                f.seek(max(0, self.pos - 4096))
                tail = f.read(self.pos - max(0, self.pos - 4096))
            nl = tail.rfind(b"\n")
            if nl >= 0:
                self._partial = tail[nl + 1 :]

    def _read_head(self) -> bytes:
        try:
            with self.path.open("rb") as f:
                return f.read(self.HEAD)
        except OSError:
            return b""

    def poll(self) -> list[str]:
        self.reset = False
        try:
            st = self.path.stat()
        except OSError:
            return []
        ident = self._identity(st)
        replaced = self._ident is not None and ident != self._ident
        if not replaced and self._head and st.st_size >= len(self._head):
            replaced = self._read_head()[: len(self._head)] != self._head
        if replaced or st.st_size < self.pos:
            self.pos = 0
            self._partial = b""
            self._head = b""
            self.resets += 1
            self.reset = True
        self._ident = ident
        if st.st_size == self.pos:
            return []
        try:
            with self.path.open("rb") as f:
                f.seek(self.pos)
                chunk = f.read(st.st_size - self.pos)
        except OSError:
            return []
        self.pos += len(chunk)
        if len(self._head) < self.HEAD:
            self._head = self._read_head()
        data = self._partial + chunk
        lines = data.split(b"\n")
        self._partial = lines.pop()  # incomplete last line (b"" when data ends with \n)
        return [ln.rstrip(b"\r").decode(self.encoding, errors="replace") for ln in lines]


# -- parsing ------------------------------------------------------------------------------


def _stamp(line: str) -> float | None:
    m = STAMP_RE.match(line)
    return float(m.group("t")) if m else None


class EventParser:
    """Feed log lines in order; get events out. Keeps state for multi-line MissionInfo."""

    def __init__(self) -> None:
        self.reward_open = False
        self._mission: dict | None = None  # {"line", "time", "head", "body": [...]}

    def reset(self) -> list[Event]:
        """The log was recreated (the game restarted)."""
        events = self._flush_mission()
        self.reward_open = False
        events.append(Event("log_reset", None, "", {}))
        return events

    def feed(self, line: str) -> list[Event]:
        events: list[Event] = []
        t = _stamp(line)
        if self._mission is not None:
            if t is None:
                self._mission["body"].append(line)
                return events
            events += self._flush_mission()

        if "Client loaded" in line and (m := LOADED_RE.search(line)):
            head = {}
            if m.group("head"):
                try:
                    head = json.loads(m.group("head"))
                except ValueError:
                    head = {}
            self._mission = {"line": line, "time": t, "head": head, "body": []}
            return events

        if any(k in line for k in REWARD_OPEN_MARKERS):
            if not self.reward_open:  # both markers can fire for one screen
                self.reward_open = True
                marker = next(k for k in REWARD_OPEN_MARKERS if k in line)
                events.append(Event("reward_screen_opened", t, line, {"marker": marker}))
            return events
        if any(k in line for k in REWARD_CLOSE_MARKERS):
            if self.reward_open:
                self.reward_open = False
                marker = next(k for k in REWARD_CLOSE_MARKERS if k in line)
                events.append(Event("reward_screen_closed", t, line, {"marker": marker}))
            return events
        if "gets reward" in line and (m := GETS_REWARD_RE.search(line)):
            item = m.group("item").replace("/Lotus/StoreItems/", "/Lotus/", 1)
            events.append(Event("reward_reported", t, line, {"player": m.group("player"), "item": item}))
            return events
        if m := LOGIN_RE.search(line):
            events.append(Event("login", t, line, {"name": m.group("name")}))
        return events

    def finish(self) -> list[Event]:
        """Call at end of input to flush a MissionInfo block still being read."""
        return self._flush_mission()

    def _flush_mission(self) -> list[Event]:
        m, self._mission = self._mission, None
        if m is None:
            return []
        body = "\n".join(m["body"]).strip()
        info: dict = {}
        if body:
            try:
                info = json.loads(body)
            except ValueError:
                # truncated or odd JSON: pull the fields we need out by hand
                for key in ("missionType", "faction", "location"):
                    if km := re.search(rf'"{key}"\s*:\s*"([^"]*)"', body):
                        info[key] = km.group(1)
        node = m["head"].get("name") or info.get("location") or None
        events = []
        if self.reward_open:  # a new mission means the old reward screen is long gone
            self.reward_open = False
            events.append(Event("reward_screen_closed", m["time"], m["line"], {"marker": "mission_loaded"}))
        events.append(
            Event(
                "mission_loaded",
                m["time"],
                m["line"],
                {
                    "node": node,
                    "missionType": info.get("missionType"),
                    "faction": info.get("faction"),
                    "mission_info": info,
                },
            )
        )
        return events


def parse_lines(lines: list[str]) -> list[Event]:
    p = EventParser()
    out: list[Event] = []
    for ln in lines:
        out += p.feed(ln)
    return out + p.finish()


def watch(
    path: Path | None = None,
    *,
    interval: float = 0.25,
    from_start: bool = False,
    on_line: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> Iterator[Event]:
    """Yield events as the game writes them. Runs until ``should_stop()`` is true."""
    tailer = LogTailer(path or default_log_path(), from_start=from_start)
    parser = EventParser()
    idle = 0
    while not should_stop():
        lines = tailer.poll()
        if tailer.reset:
            yield from parser.reset()
        for ln in lines:
            if on_line:
                on_line(ln)
            yield from parser.feed(ln)
        if lines:
            idle = 0
        else:
            idle += 1
            # a MissionInfo block ends when the next stamped line arrives; if the log
            # goes quiet right after one, emit it anyway after ~1 s
            if idle == max(1, int(1 / interval)):
                yield from parser.finish()
            time.sleep(interval)
