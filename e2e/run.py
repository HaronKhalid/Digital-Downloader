from playwright.sync_api import sync_playwright
import json, tempfile, time
from pathlib import Path
WORK = Path(tempfile.gettempdir()) / "pm-e2e"
SHOTS = Path(__file__).resolve().parent / "shots"
SHOTS.mkdir(exist_ok=True)
URL = "http://127.0.0.1:8000/"
problems, results = [], {}
def check(name, ok, detail=""):
    results[name] = ok
    print(("PASS " if ok else "FAIL ") + name + (f"  -> {detail}" if detail and not ok else ""))

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.goto(URL); page.wait_for_selector("#status[data-state='ok'], #status[data-state='warn']")
    page.screenshot(path=str(SHOTS) + "/1-empty.png")
    check("status leaves 'checking'", page.locator("#status").get_attribute("data-state") in ("ok", "warn"))
    check("input focused on load", page.evaluate("document.activeElement.id") == "url-input")
    check("card hidden initially", not page.locator("#media-card").is_visible())

    # happy path, submitted with the keyboard
    page.fill("#url-input", "https://media.example/film")
    check("Clear button appears", page.locator("#clear-button").is_visible())
    page.press("#url-input", "Enter")
    page.wait_for_selector("#media-card:not([hidden])")
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTS) + "/2-card.png")
    bottom = page.evaluate("document.querySelector('#download-button').getBoundingClientRect().bottom")
    check("download controls visible without manual scroll", bottom <= 800, str(bottom))
    check("title rendered", page.inner_text("#media-title").startswith("Prelinger Archives"))
    check("duration formatted h:mm:ss", page.inner_text("#media-duration") == "1:02:05", page.inner_text("#media-duration"))
    check("thumbnail visible", page.locator("#media-thumb-img").is_visible())
    check("quality options", page.locator("#quality-select option").all_inner_texts() == ["1080p", "720p60", "480p", "Audio only"], str(page.locator("#quality-select option").all_inner_texts()))
    check("format options for 1080p", page.locator("#format-select option").all_inner_texts() == ["MP4 · 393 MB", "WEBM · about 219 MB"], str(page.locator("#format-select option").all_inner_texts()))
    check("size shown", page.inner_text("#media-size") == "393 MB", page.inner_text("#media-size"))
    page.select_option("#format-select", "b")
    check("approx size", page.inner_text("#media-size") == "about 219 MB", page.inner_text("#media-size"))
    page.select_option("#quality-select", "480p")
    check("unknown size", page.inner_text("#media-size") == "Unknown")
    page.select_option("#quality-select", "Audio only")
    check("audio formats", [t.split(" ")[0] for t in page.locator("#format-select option").all_inner_texts()] == ["M4A", "MP3"], str(page.locator("#format-select option").all_inner_texts()))
    check("download enabled", page.locator("#download-button").is_enabled() and page.locator("#download-button").is_visible())

    # editing the URL invalidates the shown result
    page.fill("#url-input", "https://media.example/film2")
    check("card hides when URL edited", not page.locator("#media-card").is_visible())

    # hostile metadata
    page.fill("#url-input", "https://media.example/hostile"); page.click("#analyze-button")
    page.wait_for_selector("#media-card:not([hidden])"); page.wait_for_timeout(300)
    check("hostile title shown as literal text", page.inner_text("#media-title").startswith("<img src=x onerror="))
    check("no injected elements", page.locator("#media-title *").count() == 0)
    check("no script executed", page.title() != "PWNED" and "Digital Downloader" in page.title() and dialogs == [], page.title())

    # error paths
    for url, needle, name in [("https://media.example/gone", "no longer available", "unavailable media"),
                              ("http://127.0.0.1/", "private network", "SSRF attempt"),
                              ("file:///etc/passwd", "supported", "file scheme"),
                              ("not a url", "web address", "garbage"),
                              ("https://other.example/x", "isn't supported", "unsupported site")]:
        page.fill("#url-input", url); page.click("#analyze-button")
        page.wait_for_selector("#notice[data-kind='error']"); page.wait_for_timeout(150)
        txt = page.inner_text("#notice")
        check(f"error: {name}", needle in txt and "Traceback" not in txt and not page.locator("#media-card").is_visible(), txt)
    page.screenshot(path=str(SHOTS) + "/3-error.png")

    # empty submit + clear
    page.fill("#url-input", ""); page.click("#analyze-button")
    check("empty prompt", "Paste a media URL" in page.inner_text("#notice"))
    page.fill("#url-input", "x"); page.click("#clear-button")
    check("clear empties + refocuses", page.input_value("#url-input") == "" and page.evaluate("document.activeElement.id") == "url-input")

    # settings dialog
    page.click("#menu-toggle"); page.click("#open-settings"); page.wait_for_selector("#dependency-list .dependency[data-state]")
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTS) + "/4-settings.png")
    deps = page.locator("#dependency-list").inner_text()
    check("dependencies listed", all(k in deps for k in ("Backend", "Python", "FFmpeg", "Media extractor")), deps)
    page.keyboard.press("Escape")
    check("Escape closes dialog", not page.locator("#settings-dialog").is_visible())

    # ------------------------------------------------------------ downloads
    def wait_until(fn, timeout=15, label=""):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if fn():
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        return False

    jstate = lambda: page.get_attribute("#job-panel", "data-state")
    progress = lambda: int(page.get_attribute("#job-progress", "aria-valuenow"))
    outputs = lambda: sorted(p.name for p in (WORK / "out").iterdir())

    def analyze(url):
        page.fill("#url-input", url); page.click("#analyze-button")
        page.wait_for_selector("#media-card:not([hidden])")

    analyze("https://media.example/film")
    opts = page.locator("#output-select option").all_inner_texts()
    check("Save-as options for an mp4 video", opts == ["Same as source (MP4)", "MKV", "WEBM"], str(opts))
    page.select_option("#quality-select", "Audio only")
    opts = page.locator("#output-select option").all_inner_texts()
    check("Save-as options for audio (source container excluded)", opts == ["Same as source (M4A)", "MP3", "OPUS"], str(opts))
    page.select_option("#quality-select", "1080p")

    page.click("#download-button")
    page.wait_for_selector("#job-panel:not([hidden])")
    check("download button locked while a job runs", page.locator("#download-button").is_disabled() and "already running" in page.inner_text("#download-hint"))
    check("cancel visible while running", page.locator("#job-cancel").is_visible() and not page.locator("#job-open-file").is_visible())
    check("progress starts moving", wait_until(lambda: jstate() == "downloading" and progress() > 10))
    wait_until(lambda: progress() > 30)
    page.screenshot(path=str(SHOTS) + "/6-downloading.png")
    check("speed and ETA shown", "MB/s" in page.inner_text("#job-speed") and page.inner_text("#job-eta") != "—", page.inner_text("#job-speed") + "/" + page.inner_text("#job-eta"))
    check("progress bar exposes accessible value", page.get_attribute("#job-progress", "role") == "progressbar" and 0 < progress() <= 100)
    check("completes", wait_until(lambda: jstate() == "completed"))
    msg = page.inner_text("#job-message")
    name = msg.split("Saved as ", 1)[-1]
    check("completion message names the file", msg.startswith("Saved as ") and name.endswith(".mp4"), msg)
    check("saved filename is safe (title had ':')", ":" not in name and "/" not in name, name)
    check("file really exists with the right size", (WORK / "out" / name).exists() and (WORK / "out" / name).stat().st_size == 3_000_000)
    check("temp folder cleaned", list((WORK / "temp").glob("job-*")) == [])
    page.wait_for_timeout(400)  # let the width transition finish
    track = page.evaluate("document.querySelector('#job-progress').getBoundingClientRect().width")
    bar = page.evaluate("document.querySelector('#job-progress-bar').getBoundingClientRect().width")
    check("bar fills the track at 100%", abs(track - bar) < 2, f"{bar}/{track}")
    check("open buttons replace cancel", page.locator("#job-open-file").is_visible() and page.locator("#job-open-folder").is_visible() and not page.locator("#job-cancel").is_visible())
    page.screenshot(path=str(SHOTS) + "/7-completed.png")
    page.click("#job-open-file"); page.click("#job-open-folder")
    wait_until(lambda: (WORK / "open.log").exists() and len((WORK / "open.log").read_text().splitlines()) >= 2)
    log = (WORK / "open.log").read_text().splitlines()
    check("open file/folder go through the server", len(log) == 2 and log[0].startswith("file\t") and log[1].startswith("folder\t") and log[0].endswith(name), str(log))
    check("download button usable again", page.locator("#download-button").is_enabled())

    page.click("#job-another")
    check("'Download another' resets the page", not page.locator("#job-panel").is_visible() and page.input_value("#url-input") == "" and page.evaluate("document.activeElement.id") == "url-input")

    # cancel
    before = outputs()
    analyze("https://media.example/film")
    page.click("#download-button")
    wait_until(lambda: jstate() == "downloading" and progress() > 5)
    page.click("#job-cancel")
    check("cancel works", wait_until(lambda: jstate() == "cancelled"))
    check("cancelled message + retry offered", "cancelled" in page.inner_text("#job-message").lower() and page.locator("#job-retry").is_visible())
    check("cancel leaves no file and no temp dir", wait_until(lambda: list((WORK / "temp").glob("job-*")) == []) and outputs() == before, str(outputs()))
    page.click("#job-retry")
    check("'Try again' starts a new download", wait_until(lambda: jstate() in ("queued", "downloading")))
    check("...which completes", wait_until(lambda: jstate() == "completed", 20))
    check("second file never overwrote the first", len(outputs()) == len(before) + 1 and name in outputs(), str(outputs()))
    page.click("#job-another")

    # failure
    before = outputs()
    analyze("https://media.example/fail")
    page.click("#download-button")
    check("failure reached", wait_until(lambda: jstate() == "failed"))
    fm = page.inner_text("#job-message")
    check("failure is explained in plain language", "sign-in" in fm and "Traceback" not in fm, fm)
    check("failure offers retry and leaves nothing behind", page.locator("#job-retry").is_visible() and outputs() == before and list((WORK / "temp").glob("job-*")) == [])
    page.screenshot(path=str(SHOTS) + "/8-failed.png")
    page.click("#job-another")

    # conversion that FFmpeg cannot do (stub file is not real media)
    analyze("https://media.example/film")
    page.select_option("#output-select", "mkv")
    page.click("#download-button")
    wait_until(lambda: jstate() in ("queued", "downloading", "processing"))  # the NEW job, not the previous failure
    check("conversion failure reached", wait_until(lambda: jstate() == "failed", 20))
    fm = page.inner_text("#job-message")
    check("conversion error is friendly (no tool names/log text)", "couldn't be converted" in fm and "ffmpeg" not in fm.lower(), fm)
    page.click("#job-another")

    # resume after reload
    analyze("https://media.example/film")
    page.click("#download-button")
    wait_until(lambda: jstate() == "downloading" and progress() > 5)
    page.reload()
    check("running download is picked up after a reload", wait_until(lambda: page.locator("#job-panel").is_visible() and jstate() in ("downloading", "completed")))
    check("resumed download finishes", wait_until(lambda: jstate() == "completed", 20))
    page.click("#job-another")

    # hostile title through the whole flow
    analyze("https://media.example/hostile")
    page.click("#download-button")
    check("hostile-title download completes", wait_until(lambda: jstate() == "completed", 20))
    hname = page.inner_text("#job-message").split("Saved as ", 1)[-1]
    check("hostile title: safe filename, nothing executed", not any(c in hname for c in '<>:"/\\|?*') and page.title() != "PWNED", hname)
    check("hostile title shown as text in the panel", page.inner_text("#job-title").startswith("<img"))

    # mobile
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    mp = m.new_page(); mp.on("pageerror", lambda e: problems.append(f"mobile pageerror: {e}"))
    mp.goto(URL); mp.wait_for_selector("#status[data-state='ok'], #status[data-state='warn']")
    mp.fill("#url-input", "https://media.example/film"); mp.click("#analyze-button")
    mp.wait_for_selector("#media-card:not([hidden])"); mp.wait_for_timeout(300)
    mp.screenshot(path=str(SHOTS) + "/5-mobile.png", full_page=True)
    check("brand on one line (mobile)", mp.evaluate("document.querySelector('.brand').getBoundingClientRect().height") < 30)
    mp.click("#download-button")
    mp.wait_for_selector("#job-panel[data-state='completed']", timeout=20000)
    mp.wait_for_timeout(300)
    mp.screenshot(path=str(SHOTS) + "/9-mobile-done.png", full_page=True)
    overflow = mp.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    check("no horizontal scroll on mobile", not overflow)
    b.close()

print("\nbrowser console problems:", json.dumps(problems, indent=1) if problems else "none")
print(f"\n{sum(results.values())}/{len(results)} checks passed")
