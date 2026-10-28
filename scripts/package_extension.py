"""Zip the browser extension for Chrome/Edge and Firefox.

    python scripts/package_extension.py

Writes dist/digital-downloader-extension-chromium.zip and ...-firefox.zip.
(Chrome and Edge normally load the unpacked `extension/` folder directly; the zips are for sharing.)
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "extension"
OUT = ROOT / "dist"
SKIP = {"test.mjs", "manifest.firefox.json", "manifest.json"}


def build(target: str) -> Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / f"digital-downloader-extension-{target}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(SRC.rglob("*")):
            if f.is_dir() or f.name in SKIP or f.suffix == ".md":
                continue
            zf.write(f, f.relative_to(SRC).as_posix())
        if target == "firefox":
            zf.writestr("manifest.json", (SRC / "manifest.firefox.json").read_text(encoding="utf-8"))
        else:
            json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))  # fail early if broken
            zf.write(SRC / "manifest.json", "manifest.json")
    return path


if __name__ == "__main__":
    for t in ("chromium", "firefox"):
        print(build(t))
