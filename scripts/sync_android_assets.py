"""Sync web assets to Android assets folder for mobile app packaging."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ANDROID_ASSETS = ROOT / "android" / "app" / "src" / "main" / "assets"


def sync_assets() -> None:
    print(f">> Syncing frontend assets from {FRONTEND} to {ANDROID_ASSETS}...")
    if ANDROID_ASSETS.exists():
        shutil.rmtree(ANDROID_ASSETS, ignore_errors=True)
    ANDROID_ASSETS.mkdir(parents=True, exist_ok=True)

    # 1. Copy full frontend root
    for item in FRONTEND.iterdir():
        dest = ANDROID_ASSETS / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    # 2. Also create a 'static/' symlink/mirror folder for /static/... absolute resolution in WebView
    static_dest = ANDROID_ASSETS / "static"
    static_dest.mkdir(parents=True, exist_ok=True)
    for folder in ("css", "js", "img"):
        src = FRONTEND / folder
        if src.is_dir():
            shutil.copytree(src, static_dest / folder, dirs_exist_ok=True)

    print(">> Assets synced successfully!")


if __name__ == "__main__":
    sync_assets()
