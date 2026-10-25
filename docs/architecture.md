# Architecture

## Phase 0 discovery (2026-10-24)

| Item | Finding |
| --- | --- |
| Repository | Empty; created from scratch. `SCRATCHPAD.md` (the spec) was not present in the repo and should be added. |
| Dev/test OS | Linux. The target is Windows 10/11, so Windows path rules are enforced in code and tested explicitly on any OS. |
| Python | 3.12.3 |
| FFmpeg | 6.1.1 on PATH |
| Git | Available |
| Source tooling | None installed. **Open decision:** see "Source layer" below. |

## Current structure

```text
Browser UI (vanilla JS, same origin)
        │  HTTP/JSON + X-Session-Token
        ▼
FastAPI  ── LocalOnlyMiddleware (Host / Origin / token / security headers)
        ├── routes:    health, system (dependencies), media (analyze)
        ├── services:  source_service -> sources/{direct, ytdlp}   (one adapter per source type)
        │              http_client (SSRF-safe outbound HTTP), ffmpeg_service, file_service
        ├── utils:     urls (validation + SSRF), filenames (sanitizing)
        └── core:      config, logging (JSON + redaction), errors, security
```

The backend serves the frontend itself (`/` and `/static/*`), so browser and API share one origin and no CORS configuration is needed.

## Decisions and deviations from the spec

| Decision | Rationale |
| --- | --- |
| Per-run session token, Host and Origin checks on the API | `127.0.0.1` binding alone does not stop other websites in the user's browser from calling the API, and DNS rebinding bypasses it. |
| Token is injected into `index.html` by the server | Cross-origin pages cannot read it. |
| Dependency status at `/api/system/dependencies` | Keeps `/api/health` open and minimal; everything else requires the token. |
| `POST /api/media/analyze` (the interim `/validate` was removed) | Single entry point; returns normalized metadata only. |
| yt-dlp as a pinned **subprocess**, not a library | Crash isolation, easy cancellation, no extractor code inside the server process. Flags verified against the pinned version. |
| Initial sources: direct media-file links + `archive.org` | Sources that permit downloading, so the pipeline can be tested with authorized content. |
| Own `SafeHttpClient` for direct links and thumbnails | Pinned IPs, per-hop revalidation, TLS verified against the hostname, size/time/redirect limits, no https->http downgrade. |
| Thumbnails embedded as verified `data:` images | The browser never contacts a third-party host (local-first), and CSP `img-src` is `'self' data:`. SVG is refused; type is sniffed from content. |
| DRM-flagged formats filtered out at normalization | Legal boundary: protected streams are never offered. |
| Collections/playlists and live streams are refused for now | Single-item flow first; batch is a later, separate feature. |
| Interactive API docs disabled | They load scripts from a CDN, which the CSP forbids, and expose structure unnecessarily. |
| `ANALYZING` / `READY` not job states (proposal) | Analysis happens before a job exists. Decide in Phase 4: either drop them from jobs or fold analysis into job creation. |
| Settings are environment-based for now | Settings API and persistence arrive with history (Phase 6). |
| No `LICENSE` file | License choice belongs to the project owner. |

## Source layer

```text
SourceService.detect(url) -> first adapter whose can_handle(url) is true
    DirectFileSource   extension in the output allow-list; HEAD (or 1-byte Range GET) via SafeHttpClient
    YtDlpSource        host in ALLOWED_SOURCE_DOMAINS; yt-dlp --dump-single-json as a subprocess
```

Adapters return `MediaInfo` / `MediaFormat` (see `models/media.py`); the UI never sees source-specific data. `download()` is added to the adapter interface in Phase 4.

**Known limit:** yt-dlp makes its own network requests, so only the *initial* URL goes through our SSRF validation and the extractor's follow-up requests are not pinned. This is why it is restricted to an allow-list of domains rather than "any site".

**Format ids** reaching a future download step are validated against a strict pattern, and Phase 4 must additionally require the id to be one the analysis returned.

## Phase 4 design

```text
POST /api/jobs ──> JobService.create ──> queue ──> worker thread ──> DownloadService.run
   validate URL, detect source, require format_id ∈ analysis, plan (what to fetch / produce)
                                   disk check -> download part(s) [retry] -> FFmpeg? -> reserve name -> move -> cleanup
```

| Decision | Rationale |
| --- | --- |
| Job states `QUEUED → DOWNLOADING → PROCESSING → COMPLETED`, plus `FAILED` / `CANCELLED` | `ANALYZING`/`READY` dropped: analysis is a separate call before a job exists. Terminal states are final and enforced by the model. |
| In-memory registry, worker threads, `max_parallel_jobs=1` | Single local user; no Celery/Redis. Last 50 finished jobs kept; persistence arrives with history (Phase 6). |
| Only format ids returned by analysis can start a job | The browser can never smuggle a format string toward a downloader. The analysis cache is an optimisation; the server re-analyzes if needed. |
| yt-dlp downloads parts only; **our** FFmpeg merges/converts | Keeps all FFmpeg use inside one controlled path (`run_controlled`) and stops yt-dlp from doing its own post-processing. |
| Planner: video-only formats are paired with a container-compatible audio stream | Copy streams when possible (lossless, fast); fall back to re-encoding only if the copy fails. |
| Retries: 2 (after 2 s, then 5 s), only for connection loss/timeouts | Deterministic failures (404, 403, bad format, disk, too large) are never retried. A retry restarts the part; **resume is not implemented**. |
| Disk check before downloading (temp, and output if on another drive), 256 MB safety margin | Fails early with "Required X, available Y". Unknown sizes need 1 GB free. |
| Output name = sanitized title + allow-listed extension, reserved with exclusive creation | No overwrite, no race between jobs, no path influence from metadata. |
| Progress: downloading maps to 0-85% when FFmpeg follows (else 0-99%), never decreases | Smooth multi-part progress. |
| Server shutdown cancels running jobs and waits | No download or FFmpeg process outlives the server. |

## Roadmap

| Phase | Status |
| --- | --- |
| 0 Discovery | Done |
| 1 Foundation, security core | Done |
| 2 URL + source layer | Done (verified with fixtures and the real extractor's failure path; **not yet against live sites**) |
| 3 Media UI | Done (verified in headless Chromium) |
| 4 Download engine, jobs, FFmpeg processing | Done (see "Phase 4 design"; direct downloads, process control and FFmpeg verified for real; **yt-dlp downloads verified only against a fake extractor**) |
| 5 FFmpeg | Folded into Phase 4 (merge/remux/convert) |
| 5 FFmpeg processing | |
| 6 History (SQLite) | |
| 7 Security hardening | |
| 8 UX polish | |
| 9 Packaging | |

Future ideas (converters, compressors, Tauri, etc.) are intentionally not tracked here.
