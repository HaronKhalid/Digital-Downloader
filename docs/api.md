# HTTP API

Base URL: `http://127.0.0.1:8000`. All `/api` routes except `/api/health` require the header `X-Session-Token` (embedded in the served page). Errors always use:

```json
{ "error": { "code": "INVALID_URL", "message": "Human-readable explanation." } }
```

## Implemented

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/health` | `{"status": "ok"}`. No token required. |
| GET | `/api/system/dependencies` | `{backend, python, ffmpeg}` each with `ok`, `version`; FFmpeg adds `message` when missing. |
| POST | `/api/media/validate` | Body `{"url": "..."}`. Returns `{valid, normalized_url, host}` or `INVALID_URL`. Interim; becomes `/api/media/analyze` in Phase 2. |

Error codes in use: `INVALID_URL`, `INVALID_REQUEST`, `NOT_FOUND`, `PERMISSION_DENIED`, `UNKNOWN_ERROR`. The remaining codes from the spec are defined in `core/errors.py` for later phases.

## Planned

`POST /api/media/analyze`, `POST /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `GET /api/history`, `GET|PUT /api/settings`.
