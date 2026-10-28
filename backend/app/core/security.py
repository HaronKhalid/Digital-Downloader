"""Protection for the local API.

Binding to 127.0.0.1 is necessary but not sufficient: any web page open in the
user's browser can send requests to localhost, and DNS rebinding can make a
hostile site look same-origin. Three independent checks close those gaps:

* Host header must be a loopback name on our port (defeats DNS rebinding).
* A present Origin header must be one of our own origins (defeats cross-site requests).
* Every /api route except /api/health needs the per-run session token, which is
  only delivered inside the HTML served to our own origin.

The browser extension is the one deliberate exception: its two routes (EXTENSION_PATHS) accept
requests from browser-extension origins and are protected by a long random pairing key instead
of the session token. A website cannot forge an extension origin and does not know the key.
"""

from __future__ import annotations

import hmac

from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .errors import ErrorCode, error_body

SESSION_HEADER = "x-session-token"
EXTENSION_HEADER = "x-extension-key"
PUBLIC_API_PATHS = frozenset({"/api/health"})
EXTENSION_PATHS = frozenset({"/api/extension/ping", "/api/extension/send"})
EXTENSION_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _deny(message: str) -> JSONResponse:
    return JSONResponse(error_body(ErrorCode.PERMISSION_DENIED, message), status_code=403)


def _is_extension_origin(origin: str | None) -> bool:
    return bool(origin) and origin.startswith(EXTENSION_ORIGIN_PREFIXES)


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        port: int,
        session_token: str,
        extra_origins: tuple[str, ...] = (),
        extension_key=None,
    ) -> None:
        super().__init__(app)
        self._extension_key = extension_key
        self._hosts = {f"{name}:{port}" for name in ("127.0.0.1", "localhost", "[::1]")}
        self._origins = {f"http://{h}" for h in self._hosts} | set(extra_origins)
        self._token = session_token.encode()

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        on_extension_path = request.url.path in EXTENSION_PATHS
        if on_extension_path and request.method == "OPTIONS":
            # CORS preflight from the extension (Firefox needs it; Chrome usually skips it).
            if not self._host_ok(request) or not _is_extension_origin(origin) or self._extension_key is None:
                response: Response = _deny("Not allowed.")
            else:
                response = Response(status_code=204)
        else:
            response = self._check(request)
            if response is None:
                response = await call_next(request)
        if on_extension_path and _is_extension_origin(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Extension-Key"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "600"
            response.headers["Vary"] = "Origin"
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def _host_ok(self, request: Request) -> bool:
        return request.headers.get("host", "").lower() in self._hosts

    def _check(self, request: Request) -> JSONResponse | None:
        if not self._host_ok(request):
            return _deny("Requests must be sent to the local address.")
        origin = request.headers.get("origin")
        path = request.url.path
        if path in EXTENSION_PATHS:
            if self._extension_key is None:
                return _deny("The browser extension is not enabled.")
            if origin is not None and not _is_extension_origin(origin) and origin not in self._origins:
                return _deny("Requests from other websites are not allowed.")
            supplied = request.headers.get(EXTENSION_HEADER, "")
            if not self._extension_key.matches(supplied):
                return _deny("The extension is not paired. Copy the pairing code from the app's Settings into the extension.")
            return None
        if origin is not None and origin not in self._origins:
            return _deny("Requests from other websites are not allowed.")
        if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
            supplied = request.headers.get(SESSION_HEADER, "").encode()
            if not hmac.compare_digest(supplied, self._token):
                return _deny("Missing or invalid session token. Reload the page.")
        return None
