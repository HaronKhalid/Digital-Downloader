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

## History

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/history` | `{"items": [...]}` ordered by completion date descending (`limit` query param, default 50). |
| GET | `/api/history/{id}` | Single history item with metadata and `file_exists` status. |
| DELETE | `/api/history/{id}` | Deletes record from database (`{"deleted": true, "id": "..."}`). Does not delete user's downloaded media on disk. |
| POST | `/api/history/{id}/open` | Body `{"action": "file" \| "folder"}`. Safely opens the file or reveals it in the file manager. |

History item object:

```json
{
  "id": "uuid",
  "url": "https://...",
  "title": "Example Video",
  "filename": "Example_Video.mp4",
  "file_size": 15420000,
  "source": "YouTube",
  "format_label": "MP4",
  "completed_at": "2026-10-25T08:30:00Z",
  "file_exists": true
}
```

## Settings

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/settings` | Returns effective settings (`output_directory`, `allowed_source_domains`, `max_parallel_jobs`, `max_download_gb`, `log_level`). |
| PUT | `/api/settings` | Body `{"output_directory": "..."}`. Validates path and saves to SQLite `app_settings` table. |

Settings response object:

```json
{
  "output_directory": "C:\\Users\\...\\Downloads\\PersonalMedia",
  "allowed_source_domains": ["archive.org", "youtube.com"],
  "max_parallel_jobs": 1,
  "max_download_gb": 20,
  "log_level": "INFO"
}
```


## Queue, batch and extractor updates (added in Phase 1)

All routes need the `X-Session-Token` header like the rest of `/api`.

### `POST /api/jobs/batch`
Queue several links at once and pick a format automatically.

```json
{ "urls": ["https://...", "https://..."], "mode": "best" }
```
`mode` is `best` (highest resolution video) or `audio` (audio-only when the site offers it). 1 to 25 links;
duplicates are ignored. Response (HTTP 200) reports every link separately, so one bad link never blocks the rest:

```json
{ "queued": 1, "failed": 1,
  "items": [ { "url": "...", "ok": true,  "job_id": "...", "title": "...", "error": null },
             { "url": "...", "ok": false, "job_id": null, "title": null, "error": "This website isn't supported yet." } ] }
```

### `POST /api/jobs/{job_id}/retry`
Starts a fresh download from a `failed` or `cancelled` one (also after an app restart). Returns `202` with the
new `job_id`. `409` if the job is not retryable, `404` if unknown.

### Persistent queue
Unfinished downloads are saved and re-queued automatically when the app starts again (they get new ids).
Cancelling a download yourself removes it from the restore list.

### `GET /api/system/extractor/update`
```json
{ "current": "2026.10.21", "latest": "2026.11.01", "update_available": true, "supported": true }
```

### `POST /api/system/extractor/update`
Downloads the official yt-dlp binary from GitHub, verifies its SHA-256 against the release checksums, runs it to
confirm the version, then swaps it in atomically. `409` while downloads are running. The updated binary lives in
`<data>/bin/` and takes priority over the bundled one. Supported on Windows and Linux.
