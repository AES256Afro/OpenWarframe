"""Digital Extremes' official Public Export.

The index (``index_en.txt.lzma``) lists manifest file names such as
``ExportRecipes_en.json!00_<hash>``. Python's ``lzma`` rejects the index in its
auto-detect and ``FORMAT_ALONE`` modes, but the payload after the 13-byte
LZMA-alone header decodes as raw LZMA1.

Manifest file names are content addressed, so a manifest can be cached for as long
as its name stays in the index.
"""

from __future__ import annotations

import hashlib
import json
import lzma
import re
import struct
from dataclasses import dataclass

from ...http import CachedClient

BASE = "https://content.warframe.com/PublicExport/"
INDEX_URL = BASE + "index_en.txt.lzma"
MANIFEST_URL = BASE + "Manifest/"
IMAGE_BASE = "https://content.warframe.com/PublicExport"

MANIFESTS = [
    "ExportCustoms",
    "ExportDrones",
    "ExportFlavour",
    "ExportFusionBundles",
    "ExportGear",
    "ExportKeys",
    "ExportRecipes",
    "ExportRegions",
    "ExportRelicArcane",
    "ExportResources",
    "ExportSentinels",
    "ExportSortieRewards",
    "ExportUpgrades",
    "ExportWarframes",
    "ExportWeapons",
    "ExportManifest",
]

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f]")


def decode_index(raw: bytes) -> list[str]:
    """Decode the LZMA-alone index into a list of manifest file names."""
    if len(raw) < 14:
        raise ValueError("index too short to be an LZMA stream")
    props = raw[0]
    dict_size = struct.unpack("<I", raw[1:5])[0]
    filters = [
        {
            "id": lzma.FILTER_LZMA1,
            "lc": props % 9,
            "lp": (props // 9) % 5,
            "pb": props // 45,
            "dict_size": dict_size,
        }
    ]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    text = dec.decompress(raw[13:]).decode("utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_manifest_json(text: str) -> dict:
    """Parse a manifest, tolerating the raw control characters DE sometimes ships."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = _CONTROL_CHARS.sub("", text).replace("\r", "").replace("\n", "")
        return json.loads(cleaned, strict=False)


def manifest_base_name(file_name: str) -> str:
    """``ExportRecipes_en.json!00_abc`` -> ``ExportRecipes``."""
    return file_name.split("!")[0].split("_")[0].removesuffix(".json")


@dataclass
class PublicExport:
    version: str
    index: list[str]
    manifests: dict[str, dict]

    def get(self, name: str) -> dict:
        return self.manifests[name]


def fetch_public_export(
    client: CachedClient, *, names: list[str] | None = None, force: bool = False
) -> PublicExport:
    raw_index = client.get(INDEX_URL, max_age=3600, force=force)
    index = decode_index(raw_index)
    version = hashlib.sha1("\n".join(index).encode("utf-8")).hexdigest()[:12]
    wanted = set(names or MANIFESTS)
    manifests: dict[str, dict] = {}
    for file_name in index:
        base = manifest_base_name(file_name)
        if base not in wanted:
            continue
        # content addressed: cache for a long time
        body = client.get(MANIFEST_URL + file_name, max_age=30 * 86400)
        manifests[base] = parse_manifest_json(body.decode("utf-8"))
    missing = wanted - set(manifests)
    if missing:
        raise RuntimeError(f"manifests missing from index: {sorted(missing)}")
    return PublicExport(version=version, index=index, manifests=manifests)
