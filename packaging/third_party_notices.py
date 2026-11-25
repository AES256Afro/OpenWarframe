"""Write THIRD_PARTY_LICENSES.txt for a release zip.

    uv run python packaging/third_party_notices.py dist/THIRD_PARTY_LICENSES.txt

The standalone build bundles Python and every runtime dependency of openwarframe for the
platform it is built on. Most of their licenses (MIT, BSD, Apache-2.0, MPL-2.0, the PSF
license) require shipping their notice with copies, so this collects each bundled
package's license text plus Python's own. Only runtime dependencies are listed: the dev
group (pytest, ruff, PyInstaller itself) is not part of the build.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

LICENSE_NAME = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)([.\-_][^/]*)?$", re.IGNORECASE)


def runtime_distributions(root: str = "openwarframe") -> list:
    """openwarframe's dependencies for this platform, following markers but not extras."""
    seen: dict[str, object] = {}
    todo = [root]
    while todo:
        name = canonicalize_name(todo.pop())
        if name in seen:
            continue
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            continue  # a marker said yes but the package is not installed: not bundled either
        seen[name] = dist
        for spec in dist.requires or []:
            req = Requirement(spec)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                todo.append(req.name)
    seen.pop(canonicalize_name(root), None)
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def license_label(dist) -> str:
    md = dist.metadata
    if md.get("License-Expression"):
        return md["License-Expression"]
    classifiers = [c.split(" :: ")[-1] for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    lic = (md.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) < 80:
        return lic
    return ", ".join(classifiers) or "see license text"


def license_texts(dist) -> list[tuple[str, str]]:
    out = []
    for f in dist.files or []:
        if LICENSE_NAME.search(str(f).replace("\\", "/")):
            try:
                out.append((str(f), Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    if not out:
        lic = (dist.metadata.get("License") or "").strip()
        if "\n" in lic or len(lic) >= 80:  # some packages put the whole text in the metadata
            out.append(("metadata", lic))
    return out


def python_license() -> str | None:
    base = Path(sys.base_prefix)
    ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for p in (base / "LICENSE.txt", base / "LICENSE", base / "lib" / ver / "LICENSE.txt"):
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return None


def build() -> str:
    rule = "=" * 78
    parts = [
        "Third-party software bundled with OpenWarframe",
        "",
        "OpenWarframe itself is MIT licensed (see LICENSE). This build also contains the",
        "software below, each under its own license. Game data is downloaded at run time",
        "and is not part of this build; see docs/DATA_SOURCES.md.",
        "",
    ]
    py = python_license()
    parts += [
        rule,
        f"Python {sys.version.split()[0]}  (PSF License)",
        rule,
        py or "See https://docs.python.org/3/license.html",
        "",
    ]
    missing = []
    for dist in runtime_distributions():
        name, version = dist.metadata["Name"], dist.version
        texts = license_texts(dist)
        parts += [rule, f"{name} {version}  ({license_label(dist)})", rule]
        if not texts:
            missing.append(name)
            parts.append(f"License: {license_label(dist)}. No license file is shipped in the package.")
        for fname, text in texts:
            parts += [f"--- {fname} ---", text.strip(), ""]
        parts.append("")
    if missing:
        print("no license file found for:", ", ".join(missing), file=sys.stderr)
    return "\n".join(parts) + "\n"


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "THIRD_PARTY_LICENSES.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {len(runtime_distributions())} packages)")


if __name__ == "__main__":
    main()
