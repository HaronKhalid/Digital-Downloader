"""The pairing key that lets the browser extension talk to this app.

The per-run session token only exists inside the page we serve, so an extension cannot read it.
Instead the app keeps one long-lived random key on disk (readable only by the current user).
The user copies it into the extension once. Rotating it disconnects every paired browser.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
from pathlib import Path


class ExtensionKey:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._value: str | None = None

    def get(self) -> str:
        with self._lock:
            if self._value is None:
                self._value = self._read() or self._write_new()
            return self._value

    def rotate(self) -> str:
        with self._lock:
            self._value = self._write_new()
            return self._value

    def matches(self, supplied: str) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied.encode(), self.get().encode())

    def _read(self) -> str | None:
        try:
            text = self._path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text if len(text) >= 24 and text.isascii() and text.replace("-", "").replace("_", "").isalnum() else None

    def _write_new(self) -> str:
        value = secrets.token_urlsafe(32)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(value, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self._path)
        return value
