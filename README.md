# Personal Media

A local-first utility for analyzing and downloading media that you own or are authorized to download. It runs entirely on your computer: a FastAPI backend bound to `127.0.0.1` and a browser UI served by that same backend.

> **Status: All Phases (1–9) Complete.** Paste a link, analyze available streams, select quality/format, and download with live progress, real-time cancellation, FFmpeg transcode/merge/remux, and instant Open file / Folder actions.
>
> **Complete features included:**
> - **Phase 6 (History & Settings):** Completed downloads persist across restarts in SQLite with "Open file" and "Folder" buttons; Settings modal allows dynamically changing the output directory and checking dependency health.
> - **Phase 7 (Security Hardening):** Strict file permissions (`0o700` directories, `0o600` DB), no shell execution (`shell=False`), loopback binding guardrails, CSRF/session tokens, malformed-input sweep, and process-cleanup stress testing.
> - **Phase 8 (Polish):** Dark & Light theme switcher, keyboard navigation, focus trap in dialogs, ARIA announcements, and graceful empty/error states.
> - **Phase 9 (Packaging):** Windows standalone distribution with `PersonalMedia.exe` and bundled FFmpeg/FFprobe binaries so end users don't need to install anything.
>
> **Supported sources:** direct media links (`.mp4`, `.mp3`, etc.), `archive.org`, and websites supported by yt-dlp.

**Use only with content you own or have permission to download.** The application does not and will not bypass DRM, authentication, paywalls or CAPTCHAs.

## Requirements

- Windows 10/11
- Python 3.12+ (for running from source)
- Standalone release requires no prerequisites (FFmpeg and runtime are bundled)

## Quick start (Windows PowerShell)

```powershell
scripts\setup.ps1      # once: creates .venv, installs dependencies, configures FFmpeg
scripts\start.ps1      # starts http://127.0.0.1:8000 and opens your browser
```

## Building Standalone Windows Package (Phase 9)

To build the standalone `PersonalMedia.exe` and release zip with FFmpeg bundled:

```powershell
scripts\package.ps1    # produces dist/PersonalMedia/ and dist/PersonalMedia-windows-x64.zip
```

Check prerequisites any time with `scripts\check_dependencies.ps1`.

Try the real analysis pipeline on one link without starting the server:

```powershell
.venv\Scripts\python.exe scripts\analyze_url.py https://archive.org/details/<item>
```

## Manual start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements-dev.txt
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Always pass `--host 127.0.0.1`. The application refuses to start if `HOST` in the environment is not a loopback address.

## Where files go

Finished files are saved to `~/Downloads/PersonalMedia` (override with `OUTPUT_DIRECTORY` in `.env`). Work in progress lives in `data/temp/job-<id>/` and is deleted when a job ends, however it ends. Leftovers from a crash are removed at the next start. A file with an existing name is never overwritten (`Name (1).mp4`).

## Tests

```powershell
python -m pytest
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Status shows "Backend offline" | The server stopped or the page is stale. Restart `scripts\start.ps1` and reload. |
| Status shows "FFmpeg not found" | Install FFmpeg, add it to `PATH`, restart the application. |
| "Missing or invalid session token" | Reload the page. A new token is generated on every server start. |
| "Requests must be sent to the local address" | Open `http://127.0.0.1:8000/` or `http://localhost:8000/` (same port as `PORT`). |
| Port already in use | Set `PORT` in `.env` and restart. |
| "Media extractor not installed" | Re-run `scripts\setup.ps1` (installs yt-dlp). |
| A supported site stops working | Sites change often. Update yt-dlp: `pip install -U yt-dlp`, then update the pin in `backend/requirements.txt`. |
| "Not enough disk space" | Free up space on the drive that holds `data/temp` and your output folder. |
| "This website isn't supported yet" | Only direct file links and allow-listed sites work. See the status note above. |

## Documentation

- `docs/architecture.md` — design, decisions, roadmap
- `docs/security.md` — threat model, controls, residual risks
- `docs/api.md` — HTTP API
- `docs/development.md` — conventions and workflow
