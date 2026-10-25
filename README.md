# Digital Downloader

A modern, fast cross-platform utility for analyzing and downloading media from YouTube, TikTok, Instagram, Twitter/X, Facebook, direct links, and 1,000+ supported sites. It runs locally on your computer (FastAPI backend + responsive web UI) and on Android with native share-target integration.

> **Status: All Phases Complete.** Paste any link, analyze available streams, select quality/format (from 4K/1080p to audio-only), and download with live progress, real-time cancellation, FFmpeg transcode/merge/remux, and instant Open file / Folder actions.
>
> **Complete features included:**
> - **Universal Mode:** Automatic support for all media sources out of the box with zero configuration.
> - **Quality & Format Selection:** Choose from highest 4K/2K/1080p down to 144p or extract audio (MP3/M4A/AAC).
> - **Cross-Platform:** Standalone Windows desktop app (`DigitalDownloader.exe`) and Android APK with Share Target support.
> - **History & Settings:** Persistent SQLite download history with "Open file" and "Folder" shortcuts; customize output directory.
> - **Security Hardened:** Strict file permissions, safe non-shell execution (`shell=False`), loopback binding guardrails, and CSRF protection.
> - **Modern Brand Design:** Featuring Digital Takhleeq typography (Montserrat headings & Manrope body) and sleek light/dark themes.

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

## Cross-Platform Application (Desktop & Mobile)

Digital Downloader can be packaged and run across both desktop and mobile platforms:

- **Windows Desktop Application (`.exe`)**: Standalone portable app with bundled FFmpeg and Python runtime into `DigitalDownloader-windows-x64.zip`. No prerequisites required.
- **Android Mobile Application (`.apk`)**: Native Android APK with system share-target integration (tap "Share" in YouTube, TikTok, Instagram, Twitter/X to analyze immediately), MediaStore download saving, and mobile-optimized touch controls.

## GitHub Actions CI/CD Workflow

The repository includes an automated GitHub Actions workflow at [`.github/workflows/build-and-release.yml`](.github/workflows/build-and-release.yml):

- **Automated Testing**: Runs the complete unit test suite on Python 3.12 before compiling any binaries.
- **Windows Build Job**: Compiles `DigitalDownloader.exe` and bundles standalone FFmpeg binaries into `DigitalDownloader-windows-x64.zip`.
- **Android Build Job**: Bundles mobile web assets and compiles the Android APK using Gradle & Android SDK.
- **Automated Releases**: When a tag like `v1.0.0` is pushed (or triggered via manual workflow dispatch), creates a GitHub Release and attaches both the Windows `.zip` and Android `.apk` files.

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
