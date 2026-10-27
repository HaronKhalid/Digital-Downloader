# Roadmap

Status as of 2026-10-28. Estimates are planning guesses, not commitments.

## Done
- Android release signing uses one stable key from GitHub Secrets (`docs/release.md`); tag builds fail without it.
- GitHub Releases publish only for `v*` tags (or a manual run), never on a plain push to `main`.
- Default parallel downloads raised from 1 to 3.
- Honest README / release notes about Android.
- Spec scratchpad moved to `docs/archive/`.
- Phase 1 (desktop, backend + UI): persistent queue that survives restarts, retry, multi-link paste (up to 25, best quality or audio), live download list, in-app yt-dlp updater with checksum verification. MIT license added.

## Next
| Phase | Goal | Notes |
|---|---|---|
| 1b. Desktop (remaining) | Playlists, pause/resume, tray icon + notifications, brand-matched UI (navy/gold) | Single-link flow still shows one foreground panel |
| 2. Android (in progress) | Built: on-device yt-dlp + FFmpeg, foreground download service with queue (3 at once), share-to-background, notifications, MediaStore saving, honest progress, cookies, extractor update. Still to do: playlists, pause/resume, Wi-Fi-only option, per-ABI APK split | First on-device release; needs real-phone testing |
| 3. Browser extension | Manifest V3 "Send to Digital Downloader" for Chrome/Edge/Firefox, paired with the desktop app | Needs a dedicated authenticated endpoint |
| 4. Polish | Code-signed Windows build, Linux AppImage, localization, accessibility pass | |

## Known limits today
- The Android on-device engine has only been compile-checked in CI so far; test on a real phone before relying on it.
- The Android APK is large (about 2 CPU types x Python + FFmpeg).
- Windows build is not code-signed (SmartScreen warning).
