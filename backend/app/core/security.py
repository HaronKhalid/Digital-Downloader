"""Protection for the local API.

Binding to 127.0.0.1 is necessary but not sufficient: any web page open in the
user's browser can send requests to localhost, and DNS rebinding can make a
hostile site look same-origin. Three independent checks close those gaps:

* Host header must be a loopback name on our port (defeats DNS rebinding).
* A present Origin header must be one of our own origins (defeats cross-site requests).
* Every /api route except /api/health needs the per-run session token, which is
  only delivered inside the HTML served to our own origin.
"""

from __future__ import annotations

import hmac

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .errors import ErrorCode, error_body

SESSION_HEADER = "x-session-token"
PUBLIC_API_PATHS = frozenset({"/api/health"})

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


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, port: int, session_token: str, extra_origins: tuple[str, ...] = ()) -> None:
        super().__init__(app)
        self._hosts = {f"{name}:{port}" for name in ("127.0.0.1", "localhost", "[::1]")}
        self._origins = {f"http://{h}" for h in self._hosts} | set(extra_origins)
        self._token = session_token.encode()

    async def dispatch(self, request: Request, call_next):
        response = self._check(request)
        if response is None:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def _check(self, request: Request) -> JSONResponse | None:
        if request.headers.get("host", "").lower() not in self._hosts:
            return _deny("Requests must be sent to the local address.")
        origin = request.headers.get("origin")
        if origin is not None and origin not in self._origins:
            return _deny("Requests from other websites are not allowed.")
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
            supplied = request.headers.get(SESSION_HEADER, "").encode()
            if not hmac.compare_digest(supplied, self._token):
                return _deny("Missing or invalid session token. Reload the page.")
        return None
