"""Spike: download and decode Warframe's official Public Export.

DE publishes an LZMA-compressed index listing manifest file names. Python's lzma
module rejects the file in FORMAT_AUTO/FORMAT_ALONE ("Corrupt input data"), but the
payload after the 13-byte LZMA-alone header decodes fine as raw LZMA1.
"""
from __future__ import annotations

import argparse
import json
import lzma
import re
import struct
import urllib.request
from pathlib import Path

BASE = "https://content.warframe.com/PublicExport/"
UA = "OpenWarframe-spike/0.1 (+https://github.com/AES256Afro/OpenWarframe)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def decode_index(raw: bytes) -> list[str]:
    props = raw[0]
    dict_size = struct.unpack("<I", raw[1:5])[0]
    filters = [{
        "id": lzma.FILTER_LZMA1,
        "lc": props % 9,
        "lp": (props // 9) % 5,
        "pb": props // 45,
        "dict_size": dict_size,
    }]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    return dec.decompress(raw[13:]).decode("utf-8").split()


def clean_json(text: str) -> str:
    # Some manifests contain raw control characters inside strings.
    return re.sub(r"[\x00-\x08\x0b-\x1f]", "", text).replace("\n", "").replace("\r", "")


def load_manifest(index: list[str], prefix: str, out: Path) -> dict:
    name = next(n for n in index if n.startswith(prefix))
    path = out / name.split("!")[0]
    if not path.exists():
        path.write_bytes(fetch(BASE + "Manifest/" + name))
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(clean_json(text), strict=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/pe"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    index = decode_index(fetch(BASE + "index_en.txt.lzma"))
    (args.out / "index_en.txt").write_text("\n".join(index), encoding="utf-8")
    print(f"{len(index)} manifests in index")

    recipes = load_manifest(index, "ExportRecipes_en.json", args.out)["ExportRecipes"]
    regions = load_manifest(index, "ExportRegions_en.json", args.out)["ExportRegions"]
    weapons = load_manifest(index, "ExportWeapons_en.json", args.out)["ExportWeapons"]
    resources = load_manifest(index, "ExportResources_en.json", args.out)["ExportResources"]
    print(f"recipes={len(recipes)} regions={len(regions)} weapons={len(weapons)} resources={len(resources)}")

    example = next(r for r in recipes if r["resultType"].endswith("/RhinoPrime"))
    print("\nExample recipe:", example["resultType"])
    for ing in example["ingredients"]:
        print(f"  {ing['ItemCount']:>3} x {ing['ItemType']}")


if __name__ == "__main__":
    main()
