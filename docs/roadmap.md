# Roadmap

Status as of 2026-10-28. Estimates are planning guesses, not commitments.

## Done in `feature/production-hardening`
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
| 2. Android | True on-device engine (yt-dlp + FFmpeg), foreground service, queue, Share-to-background, MediaStore saving, honest progress | Replaces web-service extraction and the instant "completed" status |
| 3. Browser extension | Manifest V3 "Send to Digital Downloader" for Chrome/Edge/Firefox, paired with the desktop app | Needs a dedicated authenticated endpoint |
| 4. Polish | Code-signed Windows build, Linux AppImage, localization, accessibility pass | |

## Known limits today
- Android extraction relies on third-party public services (Invidious, Cobalt, TikWM); quality is capped and services can disappear.
- Windows build is not code-signed (SmartScreen warning).
