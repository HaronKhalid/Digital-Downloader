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
| SSRF / DNS rebinding in our own outbound requests | `SafeHttpClient`: connects only to validated, pinned IPs; every redirect hop re-validated; TLS verified against the hostname while connected to the pinned IP (tested with a real local TLS server); https->http downgrade refused; GET/HEAD only; size, time and redirect limits; proxy settings ignored | `test_http_client.py` |
| Command injection via the extractor | yt-dlp runs as an argument list with `--ignore-config --no-plugin-dirs --no-exec`, the URL placed after `--`, minimal environment, timeout, stdin closed; domain allow-list uses exact/subdomain matching | `test_sources.py` |
| Hostile extractor output | Output size capped; JSON normalized field by field; format ids and extensions must match strict patterns; non-https thumbnails dropped; DRM-flagged, storyboard and unknown-protocol formats removed; raw extractor errors are mapped to categories and never shown | `test_sources.py` |
| Malicious thumbnails | Fetched through `SafeHttpClient`, size-capped, type sniffed from content (SVG/HTML refused), embedded as `data:`; CSP forbids remote images | `test_sources.py`, `test_api.py` |
| Child processes outliving a job or the server | `run_controlled`: own process group, cancel/timeout kill the whole tree (SIGTERM, then SIGKILL sweep; `taskkill /T /F` on Windows); server shutdown cancels all jobs | `test_process_utils.py` (real processes, incl. SIGTERM-ignoring grandchildren) |
| Hostile or oversized downloads | Size capped while streaming even if the server lies about length; truncated bodies count as failures; `MAX_DOWNLOAD_GB`; disk space checked first; files never overwritten (`xb`) | `test_downloads_http.py`, `test_jobs.py` |
| Arbitrary file open/launch | `/open` takes only `file` or `folder`; the path comes from the server's job record, must be inside the output folder and have an allow-listed media extension | `test_api_jobs.py` |
| Job id guessing / aliasing | Only the canonical lowercase UUID spelling resolves; everything else is a plain 404 | `test_api_jobs.py` |
| Resource exhaustion | At most 20 queued/running jobs; one worker by default; bounded output tails | `test_api_jobs.py` |
| Leftover files after crashes | Startup removes old `job-<uuid>` folders matching our own naming only (never symlinks or other folders) | `test_jobs.py` |
| Sensitive data in logs | Structured logs emit only allow-listed fields; URLs in messages and exceptions are redacted to scheme/host/path | `test_urls.py` |
| Stack traces to the user | Global handlers return `{"error": {"code", "message"}}` only | `test_api.py` |

The suite was mutation-checked: 52 deliberate regressions of these controls (13 in Phase 1, 14 in Phase 2, 25 in Phase 4) were each caught by at least one test. A headless-browser run (`e2e/`) confirms that a hostile title (`<img onerror=...>`) renders as literal text and executes nothing.

## Residual risks and notes

- **Uvicorn can be started with a different `--host`.** Settings enforce loopback, but the CLI flag is outside the app's control. The Host-header check still rejects foreign hostnames, but always use `scripts\start.ps1`.
- **Uvicorn's access log prints request lines.** URLs currently travel in POST bodies, not query strings, so they are not logged. Keep it that way.
- **yt-dlp's own requests are not pinned.** Only the first URL passes through our validation, so it is limited to allow-listed domains. Do not add a domain you don't trust.
- **The extractor was not run against live sites during development** (no network in the build sandbox). Parsing is tested with fixtures shaped like yt-dlp output and the real subprocess's failure path; run `scripts/analyze_url.py` on a real link to confirm.
- **Direct links to any public host are allowed** (extension-based), protected by `SafeHttpClient`; the host sees your IP when you analyze it, as with any download.
- **yt-dlp needs regular updates**; an old pin will silently stop working on sites that change.
- **Filesystem permissions, process cleanup and dependency review** are Phase 7 items.
- **Windows process-tree termination** (`taskkill /T /F`) is covered only by a test of the command line it builds; it has not been executed on Windows. The POSIX path is tested with real processes.
- **yt-dlp downloads were tested against a fake extractor program**, not a live site. The command line, progress parsing, error mapping, cancellation and `%` escaping (checked against yt-dlp's real template engine) are verified; real-world behaviour is not.
- **Interrupted downloads restart from zero** (no resume). Finished jobs are forgotten on restart (history comes in Phase 6); their files stay on disk.
- **PowerShell scripts** have not been executed on Windows yet.

## Legal boundary

No DRM, encryption, authentication, paywall or CAPTCHA circumvention; no cookie or credential extraction. Sources that refuse a request must fail gracefully.
