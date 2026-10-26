# Digital Downloader v2

A modern, fast, cross-platform media downloader for YouTube, TikTok, Instagram, Twitter/X, Facebook, direct links, and 1,000+ supported sites.

> **One product. One core. Multiple platform adapters.**  
> Built as truly standalone applications for **Windows**, **Android**, and **Linux** with no external server or manual Python/FFmpeg installation prerequisites.

---

### ✨ Key Features:
- **Zero Configuration Standalone:** Works out of the box with bundled multimedia runtimes.
- **Universal Extraction:** Automatic support for all major media platforms and direct streams.
- **Quality & Format Selection:** Choose from 4K/2K/1080p down to 144p or extract audio (MP3/M4A/Opus).
- **Independent Android App:** Direct on-device extraction, native Android `DownloadManager` background downloading, system notifications, and Share Sheet integration.
- **History & Management:** Persistent download history with instant "Open file" and "Folder" actions.
- **Security Hardened:** Safe argument-list subprocess execution (`shell=False`), loopback binding guardrails (`127.0.0.1`), and path traversal sanitization.
- **Decoupled Architecture:** Clean `core/` domain engine powering platform adapters for Windows, Android, and Linux.

---

## 📱 Supported Platforms

| Platform | Format | Integration | Dependency |
|---|---|---|---|
| **Windows** | `.exe` / `.zip` | Bundled `yt-dlp` + `ffmpeg` | None (Fully Standalone) |
| **Android** | `.apk` | Native Share Target + MediaStore | None (Fully Standalone) |
| **Linux** | Standalone Binary / AppImage | Bundled runtime + local storage | None (Fully Standalone) |

---

## Quick start (Windows PowerShell)

```powershell
scripts\setup.ps1      # installs local dependencies for development
scripts\start.ps1      # starts http://127.0.0.1:8000 and opens your browser
```

---

## Architecture (v2)

Digital Downloader v2 is organized into four clean layers:

```text
┌─────────────────────────────────────────┐
│              PRESENTATION               │
│ Web UI / Desktop Shell / Android WebView│
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│             APPLICATION API             │
│ Analyze / Download / Cancel / History   │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│               CORE ENGINE               │
│ Extraction / Formats / Queue / Engine   │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│            PLATFORM ADAPTERS            │
│ Windows / Android MediaStore / Linux    │
└─────────────────────────────────────────┘
```

---

## CI/CD Workflow & Releases

The repository includes an automated GitHub Actions pipeline at [`.github/workflows/build-and-release.yml`](.github/workflows/build-and-release.yml):

- **Automated Testing**: Runs the complete 570+ unit and integration test suite across `backend/tests/` and `tests/core/`.
- **Windows Packaging**: Compiles `DigitalDownloader.exe` and bundles standalone FFmpeg binaries into `DigitalDownloader-windows-x64.zip`.
- **Android APK Build**: Syncs web assets and compiles the native Android APK (`DigitalDownloader.apk`).
- **Linux Packaging**: Packages the standalone Linux executable (`DigitalDownloader-linux-x64`).
- **Automated Releases**: Generates GitHub Releases with downloadable assets across all three platforms.

### Pushing to GitHub & Publishing Releases

1. Initialize or link your GitHub remote repository:
   ```bash
   git remote add origin https://github.com/HaronKhalid/Digital-Downloader.git
   git branch -M main
   git push -u origin main
   ```
2. To create an official cross-platform release with downloadable Windows and Android assets, create and push a tag:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
   Or go to **Actions** -> **Build & Release Digital Downloader** in your GitHub repository and click **Run workflow**.

## Local Packaging (Windows)

To build the standalone Windows release locally:

```powershell
scripts\package.ps1    # produces dist/DigitalDownloader-windows-x64.zip
```

To sync web assets into the Android project locally:

```powershell
python scripts\sync_android_assets.py
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

Finished files are saved to your chosen output folder. You can configure this directly in **Settings**:
- Short paths like `downloads\Music` or `downloads/Videos` (auto-expanded to your user profile directory).
- Home shortcuts like `~/Downloads` or full absolute paths (e.g. `D:\Media`).
- Default: `~/Downloads/PersonalMedia`.
- Mobile (Android): Saved directly to the device's native `Downloads` directory via Android DownloadManager.

Work in progress lives in `data/temp/job-<id>/` and is deleted when a job ends, however it ends. Leftovers from a crash are removed at the next start. A file with an existing name is never overwritten (`Name (1).mp4`).

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
