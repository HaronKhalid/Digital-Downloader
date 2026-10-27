# Roadmap

Status as of 2026-10-28. Estimates are planning guesses, not commitments.

## Done in `feature/production-hardening`
- Android release signing uses one stable key from GitHub Secrets (`docs/release.md`); tag builds fail without it.
- GitHub Releases publish only for `v*` tags (or a manual run), never on a plain push to `main`.
- Default parallel downloads raised from 1 to 3.
- Honest README / release notes about Android.
- Spec scratchpad moved to `docs/archive/`.

## Next
| Phase | Goal | Notes |
|---|---|---|
| 1. Desktop | Persistent queue (survives restart), pause/resume/retry, multi-URL paste, playlists, in-app yt-dlp updater, tray | In-memory queue today |
| 2. Android | True on-device engine (yt-dlp + FFmpeg), foreground service, queue, Share-to-background, MediaStore saving, honest progress | Replaces web-service extraction and the instant "completed" status |
| 3. Browser extension | Manifest V3 "Send to Digital Downloader" for Chrome/Edge/Firefox, paired with the desktop app | Needs a dedicated authenticated endpoint |
| 4. Polish | Code-signed Windows build, Linux AppImage, localization, accessibility pass | |

## Known limits today
- Android extraction relies on third-party public services (Invidious, Cobalt, TikWM); quality is capped and services can disappear.
- Windows build is not code-signed (SmartScreen warning).
- No LICENSE file yet: the owner must choose one.
