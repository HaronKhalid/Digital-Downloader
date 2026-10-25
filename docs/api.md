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

## Jobs

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/jobs` | Body `{"url", "format_id", "output_format"?}` -> `202 {"job_id", "status"}`. `format_id` must be one the analysis returned. `output_format`: `mp4` / `mkv` / `webm` for video, `mp3` / `m4a` / `opus` for audio; omit to keep the source container. |
| GET | `/api/jobs` | `{"jobs": [...]}`, newest first. |
| GET | `/api/jobs/{id}` | Job status (below). |
| POST | `/api/jobs/{id}/cancel` | Cancels a queued or running job. `409` if it already finished. |
| POST | `/api/jobs/{id}/open` | Body `{"action": "file" \| "folder"}`. Opens the finished file (or reveals it) on the machine running the app. |

Job object:

```json
{
  "job_id": "uuid", "status": "downloading", "title": "Example",
  "progress": 47.3, "stage": "Downloading video",
  "downloaded_bytes": 1234567, "total_bytes": 9876543, "speed_bps": 1048576.0, "eta_seconds": 12.0,
  "filename": null, "file_size": null, "error": null,
  "created_at": "...", "started_at": "...", "completed_at": null
}
```

`status` is one of `queued`, `downloading`, `processing`, `completed`, `failed`, `cancelled`. `filename` is only the file name, never a path. On failure `error` is `{"code", "message"}`.

Additional error codes: `FORMAT_NOT_AVAILABLE`, `DISK_SPACE_LOW`, `DOWNLOAD_FAILED`, `PROCESSING_FAILED`, `FFMPEG_NOT_FOUND`.

## Planned

`GET /api/history`, `GET|PUT /api/settings`.
