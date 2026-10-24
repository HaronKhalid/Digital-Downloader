# Security model

The backend treats every URL, title, filename and metadata field as untrusted input. This project is **not** declared "secure" until Phase 7 hardening is complete; this document records what exists today.

## Threats and controls (implemented)

| Threat | Control | Tests |
| --- | --- | --- |
| SSRF to localhost, LAN, cloud metadata | Scheme allow-list; credentials rejected; port allow-list (80/443); non-canonical numeric hosts rejected; loopback/private/link-local/CGNAT/multicast/reserved ranges blocked; IPv4-mapped, 6to4, Teredo and NAT64 unwrapped; internal hostnames and single-label names blocked; DNS answers resolved and *every* answer must be public | `test_urls.py` |
| DNS rebinding of the target | `validate_url` returns the resolved IPs for pinning; `validate_redirect` re-validates each hop. **Callers must connect to the pinned IPs.** | `test_urls.py` |
| Other websites calling the local API | Host header must be loopback on our port; Origin must be ours; `X-Session-Token` required on all `/api` routes except `/api/health` | `test_api.py` |
| Server exposed beyond the machine | `HOST` must be loopback or startup fails; start script hard-codes `127.0.0.1` | `test_api.py`, manual |
| Path traversal / arbitrary writes | Filenames sanitized to one component (NFKC, control/bidi stripped, reserved Windows names, trailing dots/spaces); `safe_join` rejects absolute, drive, `..` and symlink escapes; output extensions allow-listed | `test_security.py` |
| Job interference | Per-job temp dir named from a strictly canonical UUID; deletion only strictly inside the temp root | `test_security.py` |
| Command injection | No shell execution anywhere (enforced by a test that scans the code); subprocesses use argument lists, a timeout and a minimal environment | `test_security.py` |
| XSS from remote metadata | Frontend only uses `textContent` (enforced by a test); strict CSP with no inline scripts or styles | `test_security.py`, `test_api.py` |
| Sensitive data in logs | Structured logs emit only allow-listed fields; URLs in messages and exceptions are redacted to scheme/host/path | `test_urls.py` |
| Stack traces to the user | Global handlers return `{"error": {"code", "message"}}` only | `test_api.py` |

The suite was mutation-checked: 13 deliberate regressions of these controls were each caught by at least one test.

## Residual risks and notes

- **Uvicorn can be started with a different `--host`.** Settings enforce loopback, but the CLI flag is outside the app's control. The Host-header check still rejects foreign hostnames, but always use `scripts\start.ps1`.
- **Uvicorn's access log prints request lines.** URLs currently travel in POST bodies, not query strings, so they are not logged. Keep it that way.
- **Third-party extractors (Phase 2)** will make their own requests; see the source-layer decision in `architecture.md`.
- **Thumbnails** will load from remote hosts (`img-src https:`). A local thumbnail proxy through the validated fetch path is preferable and should be considered in Phase 3.
- **Filesystem permissions, process cleanup and dependency review** are Phase 7 items.
- **PowerShell scripts** have not been executed on Windows yet.

## Legal boundary

No DRM, encryption, authentication, paywall or CAPTCHA circumvention; no cookie or credential extraction. Sources that refuse a request must fail gracefully.
