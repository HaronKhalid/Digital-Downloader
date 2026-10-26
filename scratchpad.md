# Digital Downloader v2 — Master Scratchpad

> **Project:** Digital Downloader  
> **Current Repository:** `HaronKhalid/Digital-Downloader`  
> **Target Version:** v2.0  
> **Platforms:** Windows, Android, Linux  
> **Primary Goal:** Fully standalone applications with no dependency on a user's laptop, local network server, or manually installed Python/FFmpeg.

---

# 1. Vision

Transform the current Digital Downloader into a true cross-platform standalone application.

## Current architecture

```text
Frontend
    ↓
FastAPI server
    ↓
Python / yt-dlp / FFmpeg
    ↓
Local filesystem
```

The Android application currently depends on the development/server architecture.

## Target architecture

```text
                 DIGITAL DOWNLOADER v2
                         │
              Shared Product Architecture
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
    Windows           Android            Linux
       │                 │                 │
  Local Engine       Local Engine      Local Engine
       │                 │                 │
   PC Storage        MediaStore        Linux Storage
```

Every platform must work independently.

---

# 2. Non-Negotiable Requirements

The final application must satisfy:

- No laptop/server dependency
- No LAN dependency
- No manually installed Python
- No manually installed FFmpeg
- No manually installed yt-dlp
- Internet connection only when analyzing/downloading online media
- Standalone installation
- Native filesystem/storage integration
- Download history
- Download progress
- Cancellation
- Error handling
- Multiple quality/format options
- FFmpeg processing where required
- Mobile share integration
- Background download support on Android
- Native notifications where appropriate
- Responsive UI
- Offline UI/history access
- Automatic update strategy
- Clean release packages

---

# 3. Product Architecture

Separate the project into four conceptual layers.

```text
┌─────────────────────────────────────────┐
│              PRESENTATION               │
│                                         │
│ Web UI / Desktop UI / Mobile UI         │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│             APPLICATION API             │
│                                         │
│ Analyze / Download / Cancel / History   │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│               CORE ENGINE               │
│                                         │
│ Extraction / Formats / FFmpeg / Queue   │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│            PLATFORM ADAPTERS            │
│                                         │
│ Windows / Android / Linux / Storage     │
└─────────────────────────────────────────┘
```

The UI must never directly depend on platform-specific filesystem or downloader implementation.

---

# 4. Repository Architecture

Target structure:

```text
Digital-Downloader/
│
├── README.md
├── scratchpad.md
├── LICENSE
├── .gitignore
├── .env.example
│
├── core/
│   ├── analyzer/
│   ├── downloader/
│   ├── formats/
│   ├── jobs/
│   ├── progress/
│   ├── history/
│   ├── errors/
│   └── models/
│
├── frontend/
│   ├── index.html
│   ├── assets/
│   ├── css/
│   ├── js/
│   └── components/
│
├── backend/
│   ├── api/
│   ├── services/
│   ├── models/
│   ├── utils/
│   └── main.py
│
├── platform/
│   ├── windows/
│   ├── linux/
│   └── android/
│
├── desktop/
│   ├── windows/
│   └── linux/
│
├── android/
│   ├── app/
│   ├── gradle/
│   └── ...
│
├── scripts/
│   ├── build/
│   ├── packaging/
│   ├── assets/
│   └── release/
│
├── tests/
│   ├── core/
│   ├── backend/
│   ├── frontend/
│   └── integration/
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── android.md
│   ├── windows.md
│   ├── linux.md
│   └── release.md
│
└── .github/
    └── workflows/
        ├── test.yml
        ├── windows.yml
        ├── linux.yml
        ├── android.yml
        └── release.yml
```

Do not blindly create all directories immediately.

First refactor the current repository into these logical boundaries.

---

# 5. Core Engine

The core engine is the most important part of v2.

It should contain platform-independent concepts.

## Core responsibilities

```text
Analyze URL
    ↓
Retrieve metadata
    ↓
Retrieve available formats
    ↓
Normalize formats
    ↓
User selects format
    ↓
Create download job
    ↓
Download
    ↓
FFmpeg processing if required
    ↓
Save
    ↓
Record history
```

The core should expose operations conceptually equivalent to:

```text
analyze(url)

get_formats(media)

create_download(options)

start_download(job)

pause_download(job)       [if supported]

cancel_download(job)

get_progress(job)

get_history()

delete_history(item)
```

---

# 6. Data Models

Create consistent models.

## MediaInfo

```text
MediaInfo
├── id
├── url
├── title
├── thumbnail
├── uploader
├── duration
├── platform
└── formats[]
```

## MediaFormat

```text
MediaFormat
├── id
├── type
├── container
├── extension
├── resolution
├── width
├── height
├── fps
├── bitrate
├── filesize
├── video_codec
├── audio_codec
└── requires_merge
```

## DownloadJob

```text
DownloadJob
├── id
├── media_id
├── format_id
├── status
├── progress
├── speed
├── downloaded_bytes
├── total_bytes
├── eta
├── output_path
├── error
├── created_at
├── started_at
└── completed_at
```

Statuses:

```text
QUEUED
ANALYZING
DOWNLOADING
PROCESSING
COMPLETED
FAILED
CANCELLED
```

---

# 7. Downloader Engine

The downloader engine should be isolated from the UI.

Conceptually:

```text
Downloader
│
├── Analyzer
├── FormatSelector
├── DownloadManager
├── ProgressManager
├── FFmpegProcessor
└── JobManager
```

The engine should communicate through structured data/events rather than UI-specific code.

Example:

```text
DOWNLOAD_STARTED
DOWNLOAD_PROGRESS
DOWNLOAD_PROCESSING
DOWNLOAD_COMPLETED
DOWNLOAD_FAILED
DOWNLOAD_CANCELLED
```

---

# 8. yt-dlp Integration

The current project uses yt-dlp.

Keep yt-dlp as an extraction/download technology where appropriate, but do not expose yt-dlp-specific output directly to the frontend.

Instead:

```text
yt-dlp
   ↓
Parser / Adapter
   ↓
Normalized MediaInfo
   ↓
Frontend
```

This gives you freedom to change the underlying extraction implementation later.

## Important

Do not hard-code assumptions about a specific website's response format.

Treat supported sites as dynamic.

The application should gracefully report:

```text
Unsupported URL
Unavailable media
Private content
Region restricted
Age restricted
Authentication required
Extraction failed
Network failure
```

---

# 9. FFmpeg

FFmpeg is a core dependency for operations such as:

```text
Video + audio merging
Format conversion
Audio extraction
Container conversion
Post-processing
```

Do not require users to install FFmpeg manually.

## Windows

Bundle the required FFmpeg binary.

## Linux

Prefer a packaged/bundled strategy where legally and technically appropriate.

Also provide a fallback/documentation path for system FFmpeg.

## Android

Use an Android-compatible FFmpeg strategy rather than assuming the Windows executable can run.

The platform adapter decides how FFmpeg is invoked.

---

# 10. Platform Adapter Architecture

Create a common interface.

```text
PlatformAdapter
│
├── Storage
├── Process
├── Notifications
├── Share
├── BackgroundTasks
└── Permissions
```

Then:

```text
WindowsAdapter
AndroidAdapter
LinuxAdapter
```

Each platform implements the same conceptual API.

---

# 11. Windows Architecture

Target:

```text
DigitalDownloader.exe
```

User experience:

```text
Download installer
        ↓
Install
        ↓
Open
        ↓
Use
```

No:

```text
Python install
pip install
FFmpeg install
FastAPI server
terminal
```

## Windows components

```text
Windows App
│
├── UI
├── Local application service
├── Core engine
├── yt-dlp runtime
├── FFmpeg
├── SQLite
└── Windows filesystem adapter
```

The existing FastAPI server can remain as an internal local service during the transition.

Eventually, the desktop shell can communicate directly with the application layer if practical.

---

# 12. Windows Storage

Use sensible locations.

Example:

```text
Downloads/
    Digital Downloader/
```

Application data:

```text
AppData/
    DigitalDownloader/
        database/
        logs/
        cache/
        config/
```

Never store large temporary downloads permanently inside application installation directories.

---

# 13. Linux Architecture

Target:

```text
Digital Downloader
```

Distribution options:

### Primary

```text
AppImage
```

### Secondary

```text
.deb
```

Potential future:

```text
Flatpak
```

Start with AppImage because it is convenient for broad Linux distribution.

## Linux structure

```text
Linux App
│
├── UI
├── Core engine
├── downloader
├── FFmpeg
├── SQLite
└── Linux filesystem adapter
```

Use XDG directories for application data.

Do not hard-code Windows paths.

---

# 14. Android Architecture

Android must not connect to the Windows/Linux server.

Target:

```text
DigitalDownloader.apk
```

Architecture:

```text
Android
│
├── Native Android layer
│   ├── Activity
│   ├── Service
│   ├── Notifications
│   ├── Share Target
│   ├── MediaStore
│   └── Permissions
│
├── UI
│
└── Downloader Engine
```

---

# 15. Android UI

Reuse the existing frontend where practical.

Recommended:

```text
Web UI
   ↓
Android WebView
   ↓
JavaScript ↔ Kotlin bridge
```

The bridge should expose application operations.

Example:

```text
JS
│
├── analyze()
├── download()
├── cancel()
├── history()
└── openFile()
│
▼
Kotlin Bridge
│
▼
Android Engine
```

Do not expose arbitrary native methods to JavaScript.

Expose only the required controlled API.

---

# 16. Android Share Target

Implement:

```text
YouTube
TikTok
Instagram
Browser
Other app
       │
       │ Share
       ▼
Digital Downloader
       │
       ▼
URL extracted
       │
       ▼
Analyze
```

The user should not need to manually copy/paste the URL.

Paste should remain available as a secondary method.

---

# 17. Android Storage

Use Android's supported storage APIs.

Primary destination:

```text
Downloads/
```

Do not rely on unrestricted filesystem access.

Use Android's modern storage model.

The application should:

```text
create file
write file
show progress
complete file
register file with system
```

The completed file should appear naturally in the user's Downloads/media environment.

---

# 18. Android Background Downloads

Do not keep downloads dependent on the Activity.

Architecture:

```text
UI
 │
 ▼
Download Manager / Service
 │
 ├── Job
 ├── Progress
 ├── Cancellation
 └── Completion
```

The user should be able to minimize the app while the download continues.

Notifications:

```text
Digital Downloader
Downloading...

████████░░░░ 64%
```

Completion:

```text
Download complete
Video Name.mp4
```

---

# 19. Android Permissions

Only request permissions actually required by the Android version and storage strategy being used.

Avoid asking for broad storage access unnecessarily.

The app should explain permission requirements clearly.

---

# 20. UI Architecture

Keep the UI minimal.

## Desktop

```text
┌─────────────────────────────────────────────┐
│ Digital Downloader                          │
│                                             │
│       Paste media URL                       │
│       ┌───────────────────────────────┐     │
│       │ https://...                   │     │
│       └───────────────────────────────┘     │
│                                             │
│              [ Analyze ]                    │
│                                             │
│ ─────────────────────────────────────────── │
│                                             │
│ History                                     │
└─────────────────────────────────────────────┘
```

After analysis:

```text
┌──────────────────────┬──────────────────────┐
│ URL / Input          │ Download             │
│                      │                      │
│                      │ Thumbnail             │
│                      │ Title                 │
│                      │ Duration              │
│                      │                      │
│                      │ Quality               │
│                      │ 1080p                 │
│                      │ 720p                  │
│                      │ 480p                  │
│                      │                      │
│                      │ [ Download ]          │
└──────────────────────┴──────────────────────┘
```

---

# 21. Mobile UI

Follow the mobile layout already planned.

```text
Logo

Paste URL
┌───────────────────────────┐
│ Paste URL                 │
└───────────────────────────┘

[ Analyze ]
```

After analysis:

```text
Thumbnail

Title
Duration

Quality
1080p
720p
480p

[ Download ]
```

After clicking download:

```text
Downloading...

████████████░░░

1080p
12.4 MB/s
ETA 00:08
```

After completion:

```text
✓ Download complete

[ Open ]

[ Share ]
```

---

# 22. History

History must be platform-independent conceptually.

```text
History
│
├── Title
├── Thumbnail
├── Format
├── Date
├── Status
└── Open file
```

Example:

```text
Today

Video Name
1080p MP4
Completed

Yesterday

Another Video
720p MP4
Completed
```

Store metadata in SQLite.

Do not store actual media files inside the database.

---

# 23. Queue System

Implement a proper job queue.

Example:

```text
Queue
│
├── Job 1 — Downloading
├── Job 2 — Queued
└── Job 3 — Queued
```

Future controls:

```text
Pause
Resume
Cancel
Retry
Remove
```

Initial version may support only:

```text
Download
Cancel
Retry
```

Do not over-engineer v2.

---

# 24. Error Handling

Never show raw stack traces to users.

Instead:

```text
Could not analyze this URL.

Possible reasons:
• URL is invalid
• Content is unavailable
• Network connection failed
• Content requires authentication
• Source is temporarily unavailable
```

Developer logs can contain detailed errors.

---

# 25. Logging

Create:

```text
logs/
```

Log:

```text
Application startup
Analysis request
Download started
Download completed
Download failed
FFmpeg failure
Storage failure
Unexpected exception
```

Never log sensitive information unnecessarily.

---

# 26. Configuration

Create a configuration layer.

Example:

```text
Config
├── download_directory
├── concurrent_downloads
├── preferred_format
├── preferred_quality
├── notifications
├── theme
└── language
```

Do not hard-code these throughout the application.

---

# 27. API Boundary

If FastAPI remains in the Windows/Linux desktop architecture initially, treat it as an **internal application API**, not a public server.

Example:

```text
127.0.0.1
```

Only the local application communicates with it.

Do not expose:

```text
0.0.0.0
```

by default.

No public API should be created unless a cloud architecture is intentionally added later.

---

# 28. Development Modes

Support three modes.

## Development

```text
Frontend
    ↓
Local backend
    ↓
Core
```

Easy debugging.

## Desktop production

```text
Desktop shell
    ↓
Bundled local engine
```

## Android production

```text
Android UI
    ↓
Native bridge
    ↓
Android engine
```

---

# 29. Build System

Create platform-specific build scripts.

```text
scripts/build/
    build-windows
    build-linux
    build-android
```

Conceptually:

```text
build-all
    │
    ├── test
    ├── build Windows
    ├── build Linux
    └── build Android
```

---

# 30. GitHub Actions

Target pipeline:

```text
Push / Tag
     │
     ▼
Tests
     │
     ├─────────────┬─────────────┐
     ▼             ▼             ▼
 Windows         Linux        Android
     │             │             │
 .exe/.zip       AppImage       APK/AAB
     │             │             │
     └─────────────┴─────────────┘
                     │
                     ▼
              GitHub Release
```

Release naming:

```text
DigitalDownloader-v2.0.0-windows-x64.exe

DigitalDownloader-v2.0.0-linux-x64.AppImage

DigitalDownloader-v2.0.0-android-arm64.apk
```

Use appropriate architecture variants as needed.

---

# 31. Versioning

Use semantic versioning.

```text
MAJOR.MINOR.PATCH
```

Examples:

```text
1.0.0
1.1.0
1.1.1
2.0.0
```

v2 represents the architectural transition to standalone multi-platform operation.

---

# 32. Testing Strategy

Do not test only the UI.

## Unit tests

Test:

```text
Format parsing
URL validation
Job state
Progress calculation
Configuration
History
```

## Integration tests

Test:

```text
URL
 ↓
Analyzer
 ↓
Format
 ↓
Downloader
 ↓
FFmpeg
 ↓
Storage
 ↓
History
```

## Platform tests

Windows:

```text
Install
Analyze
Download
Cancel
History
Open file
```

Android:

```text
Install
Paste
Share
Analyze
Download
Background
Notification
Storage
History
```

Linux:

```text
Install
Analyze
Download
Storage
History
```

---

# 33. Offline Behavior

The application should open without internet.

Available offline:

```text
UI
History
Settings
Previously downloaded files
```

Unavailable offline:

```text
New URL analysis
New online downloads
```

Show:

```text
No internet connection.
Connect to the internet to analyze this URL.
```

---

# 34. Security

Treat every URL as untrusted input.

Implement:

```text
URL validation
Safe subprocess execution
No shell string concatenation
Safe temporary directories
Controlled file names
Path traversal protection
```

Never construct commands like:

```text
shell = "ffmpeg " + user_input
```

Use argument arrays/process APIs.

Sanitize filenames.

Example:

```text
../../malicious.exe
```

must never escape the download directory.

---

# 35. Temporary Files

Use a dedicated temporary directory:

```text
temp/
```

Workflow:

```text
Download
   ↓
Temporary file
   ↓
FFmpeg processing
   ↓
Final file
   ↓
Delete temporary files
```

If a job fails, clean up partial files where safe.

---

# 36. Performance

Optimize for:

```text
Low RAM usage
Low CPU when idle
Fast startup
Minimal UI overhead
Efficient downloads
```

Do not preload unnecessary resources.

On mobile:

```text
Battery efficiency
Background limitations
Network changes
Storage space
```

must be considered.

---

# 37. Storage Space

Before starting a large download, estimate:

```text
Required space
Available space
```

If insufficient:

```text
Not enough storage space.

Required: 2.4 GB
Available: 1.1 GB
```

Do not start the download.

---

# 38. Network Changes on Android

Handle:

```text
Wi-Fi → Mobile Data
Mobile Data → Wi-Fi
Network lost
Network restored
```

At minimum:

```text
Detect failure
Show state
Allow retry
```

Advanced resume support can be implemented later.

---

# 39. Theme

Support:

```text
Dark
Light
System
```

Keep your existing Digital Downloader visual identity.

Do not redesign the product unnecessarily during the architecture migration.

---

# 40. Accessibility

Include:

```text
Readable text
Keyboard navigation on desktop
Visible focus states
Accessible buttons
Meaningful labels
Good contrast
```

Mobile controls should have appropriate touch targets.

---

# 41. Localization

Do not fully translate v2 initially.

But structure the UI so text can eventually come from:

```text
i18n/
    en.json
```

Future:

```text
ur.json
ar.json
...
```

---

# 42. Analytics

Do not add invasive tracking by default.

For a standalone downloader, privacy is a product advantage.

If analytics are ever added:

```text
Opt-in
Anonymous
Minimal
Clearly disclosed
```

---

# 43. Cloud Architecture

Do NOT implement cloud processing in v2 unless there is a specific business reason.

Future architecture could become:

```text
Mobile
Windows
Linux
Web
   │
   ▼
Cloud API
   │
   ├── Queue
   ├── Workers
   ├── yt-dlp
   ├── FFmpeg
   └── Storage
```

But this is v3+ territory.

---

# 44. Platform Matrix

| Feature | Windows | Linux | Android |
|---|---:|---:|---:|
| Standalone | ✓ | ✓ | ✓ |
| Local processing | ✓ | ✓ | ✓ |
| URL analysis | ✓ | ✓ | ✓ |
| Downloads | ✓ | ✓ | ✓ |
| FFmpeg | ✓ | ✓ | ✓ |
| History | ✓ | ✓ | ✓ |
| Queue | ✓ | ✓ | ✓ |
| Cancel | ✓ | ✓ | ✓ |
| Notifications | Optional | Optional | ✓ |
| Share Target | N/A | N/A | ✓ |
| Native storage | ✓ | ✓ | ✓ |
| Background download | ✓ | ✓ | ✓ |
| No laptop dependency | ✓ | ✓ | ✓ |

---

# 45. Migration Strategy

Do NOT delete the existing working application immediately.

Use:

```text
current version
      │
      ▼
refactor
      │
      ▼
v2 branch
      │
      ▼
test
      │
      ▼
release
```

Create:

```text
main
develop
feature/*
release/*
```

Recommended:

```text
main
    production

develop
    v2 development
```

---

# 46. Migration Order

## Step 1

Freeze the current working version.

Tag:

```text
v1.0.0
```

Do this before major architectural changes.

---

## Step 2

Document the current system.

Record:

```text
Frontend endpoints
Backend endpoints
yt-dlp calls
FFmpeg calls
Storage locations
Android communication
Build scripts
CI/CD
```

---

## Step 3

Extract shared models.

Create:

```text
MediaInfo
MediaFormat
DownloadJob
DownloadProgress
HistoryItem
```

---

## Step 4

Create the core engine boundary.

Separate:

```text
business logic
```

from:

```text
HTTP
UI
filesystem
platform
```

---

## Step 5

Refactor Windows.

Keep the existing functionality working.

Test:

```text
Analyze
Download
FFmpeg
History
```

---

## Step 6

Build Android independently.

Remove:

```text
Laptop → Android
```

dependency.

Implement:

```text
Android → local engine
```

---

## Step 7

Build Linux.

Reuse the core engine.

Implement Linux-specific packaging/storage.

---

## Step 8

Implement native integrations.

Android:

```text
Share Target
MediaStore
Notifications
Background downloads
```

Windows:

```text
Filesystem
Notifications
Installer
```

Linux:

```text
Filesystem
Desktop integration
```

---

## Step 9

Automate builds.

GitHub Actions:

```text
Windows
Linux
Android
```

---

## Step 10

Release beta.

```text
v2.0.0-beta.1
```

Test with real users.

Then:

```text
v2.0.0
```

---

# 47. Definition of Done

Digital Downloader v2 is complete when:

## Windows

```text
Fresh Windows installation
        ↓
Install Digital Downloader
        ↓
Open
        ↓
Paste URL
        ↓
Analyze
        ↓
Select quality
        ↓
Download
        ↓
File appears in Downloads
```

No Python/FFmpeg setup required.

---

## Android

```text
Fresh Android phone
        ↓
Install APK
        ↓
Open
        ↓
Paste OR Share URL
        ↓
Analyze
        ↓
Select quality
        ↓
Download
        ↓
Minimize app
        ↓
Notification
        ↓
Download complete
        ↓
File appears in Downloads
```

No laptop.

No local server.

No same-Wi-Fi requirement.

---

## Linux

```text
Fresh Linux machine
        ↓
Install/run AppImage
        ↓
Open
        ↓
Paste URL
        ↓
Analyze
        ↓
Download
        ↓
File saved locally
```

No manual Python/FFmpeg configuration for the primary distribution.

---

# 48. Final Architecture

The final mental model should be:

```text
                         DIGITAL DOWNLOADER
                                │
                    ┌───────────┴───────────┐
                    │     SHARED CORE       │
                    │                       │
                    │ Media Analysis        │
                    │ Format Selection      │
                    │ Download Jobs         │
                    │ Progress              │
                    │ FFmpeg Processing      │
                    │ History               │
                    │ Error Handling        │
                    └───────────┬───────────┘
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
         WINDOWS             ANDROID             LINUX
             │                  │                  │
       Platform Adapter   Platform Adapter   Platform Adapter
             │                  │                  │
             ▼                  ▼                  ▼
        PC Storage          MediaStore        Linux Storage
             │                  │                  │
             └──────────────────┴──────────────────┘
                                │
                         User's Device
```

The central principle is:

> **One product. One core. Multiple platform adapters.**

Not:

> One server that every device depends on.

---

# 49. Immediate Next Task

Do not start coding Android immediately.

First perform this migration in order:

```text
CURRENT REPOSITORY
       ↓
Audit existing files
       ↓
Map current architecture
       ↓
Identify backend responsibilities
       ↓
Identify frontend responsibilities
       ↓
Identify Android responsibilities
       ↓
Extract shared core
       ↓
Create platform abstraction
       ↓
Refactor Windows
       ↓
Build standalone Android
       ↓
Build Linux
       ↓
Automate releases
```

The first implementation milestone should therefore be:

```text
MILESTONE 1

"Core Extraction"

Goal:

The existing Windows application continues working,
but its downloader/business logic is no longer tightly
coupled to FastAPI or the frontend.
```

Only after that milestone is stable should Android development begin.

---

# 50. Product Principle

Digital Downloader should ultimately feel like:

```text
                  INSTALL
                     ↓
                   OPEN
                     ↓
             PASTE OR SHARE URL
                     ↓
                  ANALYZE
                     ↓
              SELECT FORMAT
                     ↓
                 DOWNLOAD
                     ↓
                  COMPLETE
```

The complexity should exist **inside the architecture**, not in the user's experience.

The user should never know whether the application internally uses Python, Kotlin, yt-dlp, FFmpeg, a native engine, or another implementation.

They should only know:

> **Digital Downloader works.**