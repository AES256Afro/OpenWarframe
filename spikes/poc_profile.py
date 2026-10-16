"""Spike: fetch the public profile for an account ID and summarize progression.

The endpoint is the one the in-game profile viewer uses. It is read-only and needs
only the 24-character account ID (the `gid` cookie on warframe.com when logged in).
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path

HOSTS = {
    "pc": "https://api.warframe.com/cdn/getProfileViewingData.php",
    "ps4": "http://content-ps4.warframe.com/dynamic/getProfileViewingData.php",
    "xb1": "http://content-xb1.warframe.com/dynamic/getProfileViewingData.php",
    "swi": "http://content-swi.warframe.com/dynamic/getProfileViewingData.php",
    "mob": "http://content-mob.warframe.com/dynamic/getProfileViewingData.php",
    "and": "http://content-and.warframe.com/dynamic/getProfileViewingData.php",
}
UA = "OpenWarframe-spike/0.1 (+https://github.com/AES256Afro/OpenWarframe)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-id", required=True)
    ap.add_argument("--platform", choices=HOSTS, default="pc")
    ap.add_argument("--out", type=Path, default=Path("data/profile"))
    args = ap.parse_args()
    if not re.fullmatch(r"[0-9a-f]{24}", args.account_id):
        raise SystemExit("account id must be 24 lowercase hex characters")

    url = f"{HOSTS[args.platform]}?playerId={args.account_id}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
        print("Cache-Control:", resp.headers.get("Cache-Control"))
    if not body:
        raise SystemExit("empty response: wrong platform or unknown account id")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "profile.raw.json").write_bytes(body)
    data = json.loads(body.decode("utf-8"))
    r = data["Results"][0]

    xp = r.get("LoadOutInventory", {}).get("XPInfo", [])
    missions = r.get("Missions", [])
    print(
        f"\nMastery rank: {r.get('PlayerLevel')}   items with XP: {len(xp)}   nodes with completions: {len(missions)}"
    )
    cats = Counter(x["ItemType"].split("/")[3] if x["ItemType"].count("/") > 3 else "?" for x in xp)
    print("XP entries by top-level path:", dict(cats.most_common(8)))
    print("Syndicates:", [(a.get("Tag"), a.get("Title")) for a in r.get("Affiliations", [])][:12])
    print("Intrinsics:", r.get("PlayerSkills"))
    print("Achievements tracked:", len(r.get("ChallengeProgress", [])))
    print("Stats keys:", sorted(data.get("Stats", {}).keys())[:25])


if __name__ == "__main__":
    main()
