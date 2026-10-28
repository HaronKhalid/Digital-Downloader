# Installing without warnings getting in the way

Digital Downloader is not commercially code-signed (a certificate costs roughly US$200–600 per year). That is the
only reason Windows and Android show warnings. These are the steps that make it work, plus what the build already
does to look as trustworthy as possible.

## Windows 11

1. Download `DigitalDownloader-Setup.exe` (or the portable `.zip`) from the Releases page.
2. **SmartScreen** ("Windows protected your PC"): click **More info → Run anyway**.
3. **Edge / Chrome says "not commonly downloaded"**: press **Keep** (Edge: `…` → Keep → Keep anyway).
4. **Windows Security removed a file**: *Virus & threat protection → Protection history → Restore*, then
   *Manage settings → Exclusions → Add folder* and pick the Digital Downloader folder
   (installed copy: `%LOCALAPPDATA%\Digital Downloader`).
5. Files downloaded with a browser carry a "from the internet" mark. For the portable zip, right-click the zip →
   **Properties → Unblock → OK** *before* unzipping.

What the build does to reduce false alarms: a folder build instead of a self-extracting single file, no UPX
packing, a proper Windows version resource (publisher, product, version), no `.bat`/`.vbs` helpers, and an automatic
start-up self-test in CI. Reputation improves as more people run the same release; the only complete fix is code signing.

## Android

1. Open the downloaded `DigitalDownloader.apk` → allow **Install unknown apps** for your browser/Files app when asked.
2. **Play Protect** "Blocked / App not verified": tap **More details → Install anyway**.
   (Settings → Security → Play Protect → can also be paused briefly while installing.)
3. Always install updates **over** the existing app. This works only when every release is signed with the **same
   key**; keep your keystore and its password backed up safely (never in the repository).

## Browser extension

Follow `extension/README.md`. Chrome and Edge only need *Developer mode → Load unpacked*; nothing is uploaded to a store.

## If you make the repository private

Releases stay downloadable for you when logged in. The app's built-in update check for yt-dlp is unaffected.
