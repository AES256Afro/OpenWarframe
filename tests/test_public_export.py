from __future__ import annotations

import lzma

from openwarframe.sources.static.public_export import decode_index, manifest_base_name, parse_manifest_json


def test_decode_index_reads_lzma_alone_payload():
    text = "ExportRecipes_en.json!00_abc\r\nExportRegions_en.json!00_def\r\n"
    raw = lzma.compress(text.encode(), format=lzma.FORMAT_ALONE)
    assert decode_index(raw) == ["ExportRecipes_en.json!00_abc", "ExportRegions_en.json!00_def"]


def test_manifest_base_name():
    assert manifest_base_name("ExportRecipes_en.json!00_abc") == "ExportRecipes"
    assert manifest_base_name("ExportManifest.json!00_abc") == "ExportManifest"


def test_parse_manifest_tolerates_control_characters():
    dirty = '{"ExportResources": [{"name": "Bad\x01Name\r\nHere", "uniqueName": "/x"}]}'
    data = parse_manifest_json(dirty)
    assert data["ExportResources"][0]["name"] == "BadNameHere"
