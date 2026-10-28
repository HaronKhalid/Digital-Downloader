# Digital Downloader – browser extension

Send the page or link you are looking at to the Digital Downloader app on your computer.
It talks only to `127.0.0.1` (your own PC). Nothing goes to any server.

## Install (one time, about a minute)

**Chrome / Edge / Brave**
1. Open `chrome://extensions` (Edge: `edge://extensions`) and switch on **Developer mode**.
2. Press **Load unpacked** and choose this `extension` folder
   (in the app: *Settings → Browser extension → Open extension folder*).
3. Pin the icon (puzzle piece → pin).

**Firefox**
1. Run `python scripts/package_extension.py` to get `dist/digital-downloader-extension-firefox.zip`.
2. Open `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on** → pick `manifest.json` from the unzipped
   folder (or the zip). Firefox removes temporary add-ons when it restarts; a permanent install needs Mozilla signing.

## Pair it (one time)
1. In the app open **Settings → Browser extension** and press **Copy code**.
2. Click the extension icon, paste the code, press **Connect**.

## Use it
- Click the icon → **Download video** or **Audio only**.
- Right-click a page, video or link → **Download … with Digital Downloader**.
- Keyboard: **Alt+Shift+D** sends the current tab (change it at `chrome://extensions/shortcuts`).
- The icon shows ✓ when queued, ! if something is wrong (app closed, code outdated).

## Safety
- The pairing code is a long random secret stored only on your computer. Websites cannot read it.
- Each "Make a new code" in the app instantly disconnects every extension that used the old one.
- The app only accepts requests from browser extensions that know the code, never from web pages.

## Development
`node extension/test.mjs` runs the logic tests. `python scripts/package_extension.py` builds the zips.
