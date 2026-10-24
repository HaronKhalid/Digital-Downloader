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
        ├── routes:    health, system (dependencies), media (validate)
        ├── services:  ffmpeg_service (detection), file_service (path safety)
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
| `POST /api/media/validate` as an interim endpoint | Exercises the security core end to end now. Phase 2 grows it into `/api/media/analyze`. |
| Interactive API docs disabled | They load scripts from a CDN, which the CSP forbids, and expose structure unnecessarily. |
| `ANALYZING` / `READY` not job states (proposal) | Analysis happens before a job exists. Decide in Phase 4: either drop them from jobs or fold analysis into job creation. |
| Settings are environment-based for now | Settings API and persistence arrive with history (Phase 6). |
| No `LICENSE` file | License choice belongs to the project owner. |

## Source layer (open decision, needed for Phase 2)

Nothing yet extracts metadata or media. The likely choice is `yt-dlp`, which is also the largest dependency and attack surface. Before Phase 2, decide:

1. Library or subprocess use (subprocess with argument arrays isolates crashes and is easier to cancel).
2. Pin the version and plan frequent updates.
3. Initial in-scope sources. Suggested: direct HTTP(S) media-file URLs plus one or two providers that permit downloading, so the pipeline can be tested end to end with authorized content.
4. Because a third-party extractor makes its own network requests, our SSRF controls only cover the initial URL unless requests are made through our own pinned-IP client. Prefer an allow-list of domains for extractor-handled sources.

## Roadmap

| Phase | Status |
| --- | --- |
| 0 Discovery | Done |
| 1 Foundation, security core | Done |
| 2 URL + source layer | Next (blocked on source decision) |
| 3 Media UI | |
| 4 Download engine, jobs | |
| 5 FFmpeg processing | |
| 6 History (SQLite) | |
| 7 Security hardening | |
| 8 UX polish | |
| 9 Packaging | |

Future ideas (converters, compressors, Tauri, etc.) are intentionally not tracked here.
