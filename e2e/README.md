# Browser end-to-end check (optional)

Drives the real UI in headless Chromium against the real app, with a stubbed media source
(so no network is needed). Includes a hostile-title XSS check, error paths, keyboard use,
the settings dialog and a mobile layout check. Screenshots go to `e2e/shots/`.

```powershell
pip install playwright
playwright install chromium
python e2e/server.py          # terminal 1: app on http://127.0.0.1:8000 with stub source
python e2e/run.py             # terminal 2: runs the checks
```
