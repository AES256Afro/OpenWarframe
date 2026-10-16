"""Spike: fetch the official world state and resolve active fissures to node names."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

WORLDSTATE = "https://api.warframe.com/cdn/worldState.php"
UA = "OpenWarframe-spike/0.1 (+https://github.com/AES256Afro/OpenWarframe)"
TIER = {
    "VoidT1": "Lith",
    "VoidT2": "Meso",
    "VoidT3": "Neo",
    "VoidT4": "Axi",
    "VoidT5": "Requiem",
    "VoidT6": "Omnia",
}


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pe", type=Path, default=Path("data/pe"), help="directory written by poc_public_export.py"
    )
    args = ap.parse_args()

    regions = json.loads((args.pe / "ExportRegions_en.json").read_text(encoding="utf-8"))["ExportRegions"]
    nodes = {n["uniqueName"]: n for n in regions}

    ws = fetch_json(WORLDSTATE)
    print(f"world state sections: {len(ws)}  (build {ws.get('BuildLabel', '?')})")
    now_ms = time.time() * 1000
    print("\nActive fissures:")
    for f in sorted(ws["ActiveMissions"], key=lambda f: f["Modifier"]):
        node = nodes.get(f["Node"], {})
        mins = (int(f["Expiry"]["$date"]["$numberLong"]) - now_ms) / 60000
        sp = "  Steel Path" if f.get("Hard") else ""
        print(
            f"  {TIER.get(f['Modifier'], f['Modifier']):8} {f['MissionType']:<22} {node.get('name', f['Node'])} ({node.get('systemName', '?')})  {mins:4.0f} min left{sp}"
        )

    live = ("Alerts", "Invasions", "Sorties", "LiteSorties", "VoidTraders", "SyndicateMissions", "Goals")
    print("\nOther live sections present:", ", ".join(k for k in live if ws.get(k)))


if __name__ == "__main__":
    main()
