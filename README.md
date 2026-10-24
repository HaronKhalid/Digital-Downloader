# Personal Media

A local-first utility for analyzing and downloading media that you own or are authorized to download. It runs entirely on your computer: a FastAPI backend bound to `127.0.0.1` and a browser UI served by that same backend.

> **Status: Phase 1 complete (foundation + security core).** The app starts, serves the UI, checks dependencies, and validates URLs with SSRF protection. Media analysis, downloads, jobs, history and FFmpeg processing are not implemented yet. See `docs/architecture.md` for the roadmap.

**Use only with content you own or have permission to download.** The application does not and will not bypass DRM, authentication, paywalls or CAPTCHAs.

## Requirements

- Windows 10/11 (developed and tested on Linux; see "Platform notes")
- Python 3.12+
- FFmpeg on your `PATH` (needed from Phase 5 onward; detected and reported today)

## Quick start (Windows PowerShell)

```powershell
scripts\setup.ps1      # once: creates .venv, installs dependencies, creates .env
scripts\start.ps1      # starts http://127.0.0.1:8000 and opens your browser
```

Check prerequisites any time with `scripts\check_dependencies.ps1`.

## Manual start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements-dev.txt
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Always pass `--host 127.0.0.1`. The application refuses to start if `HOST` in the environment is not a loopback address.

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

## Documentation

- `docs/architecture.md` — design, decisions, roadmap
- `docs/security.md` — threat model, controls, residual risks
- `docs/api.md` — HTTP API
- `docs/development.md` — conventions and workflow
