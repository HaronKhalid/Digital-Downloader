"""Run the REAL analysis pipeline on one URL and print the normalized result.

    python scripts/analyze_url.py https://archive.org/details/<item>

No server needed. Uses the same validation, source detection and extractor as the app,
so it is the quickest way to see what a link produces (or why it fails).
"""

import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.errors import AppError  # noqa: E402
from backend.app.services.source_service import build_source_service  # noqa: E402
from backend.app.utils.urls import validate_url  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    settings = get_settings()
    try:
        checked = validate_url(sys.argv[1], allowed_ports=settings.allowed_ports)
        service = build_source_service(settings)
        source = service.detect(checked)
        print(f"Source adapter: {source.id if source else 'none'}", file=sys.stderr)
        info = service.analyze(checked)
    except AppError as exc:
        print(f"[{exc.code.value}] {exc.message}", file=sys.stderr)
        if exc.reason:
            print(f"  reason: {exc.reason}", file=sys.stderr)
        return 1
    data = dataclasses.asdict(info)
    if data.get("thumbnail"):
        data["thumbnail"] = data["thumbnail"][:40] + "... (embedded image)"
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
