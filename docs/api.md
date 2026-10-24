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
| POST | `/api/media/analyze` | Body `{"url": "..."}`. Validates, detects the source and returns normalized metadata (below). |

`/api/system/dependencies` also reports `extractor` (yt-dlp) with the same `ok` / `version` / `message` shape.

### `POST /api/media/analyze` response

```json
{
  "source": "ytdlp",
  "source_label": "Web media",
  "url": "https://archive.org/details/example",
  "title": "Example",
  "duration": 125,
  "thumbnail": "data:image/png;base64,...",
  "formats": [
    {"id": "mp4-720", "type": "video", "container": "mp4", "resolution": "720p",
     "has_audio": true, "filesize": 10000000, "filesize_approximate": false, "label": "720p · MP4"}
  ]
}
```

`duration`, `thumbnail`, `resolution` and `filesize` may be `null`. `title` is untrusted text: render it with `textContent`.

Error codes in use: `INVALID_URL`, `INVALID_REQUEST`, `NOT_FOUND`, `PERMISSION_DENIED`, `UNSUPPORTED_SOURCE`, `SOURCE_UNAVAILABLE`, `MEDIA_NOT_AVAILABLE`, `TIMEOUT`, `UNKNOWN_ERROR`. The remaining codes from the spec are defined in `core/errors.py` for later phases.

## Planned

`POST /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `GET /api/history`, `GET|PUT /api/settings`.
