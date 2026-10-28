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

    outputs = lambda: sorted(p.name for p in (WORK / "out").iterdir())
    rows = lambda: page.locator("#queue-list > li")
    states = lambda: [r.get_attribute("data-state") for r in rows().all()]
    first_state = lambda: rows().first.get_attribute("data-state")
    first_progress = lambda: int(rows().first.locator(".queue-bar").get_attribute("aria-valuenow"))
    btn = lambda row, label: row.locator("button", has_text=label)

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
    page.wait_for_selector("#queue-section:not([hidden]) #queue-list > li")
    check("download appears in the Downloads list", rows().count() == 1)
    check("screen is reset after starting (card hidden, box empty)", not page.locator("#media-card").is_visible() and page.input_value("#url-input") == "")
    check("no separate history block on the main screen", page.locator("#history-section").count() == 0 and not page.locator("#view-history").is_visible())
    check("cancel visible while running", btn(rows().first, "Cancel").is_visible() and not btn(rows().first, "Open").is_visible())
    check("progress starts moving", wait_until(lambda: first_state() == "downloading" and first_progress() > 10))

    # THE bug: analyzing another link must not make the running download vanish
    analyze("https://media.example/film")
    check("running download stays visible while another link is analyzed", rows().count() == 1 and rows().first.is_visible())
    page.screenshot(path=str(SHOTS) + "/6-downloading.png")
    page.click("#download-button")
    check("a second download runs alongside the first", wait_until(lambda: rows().count() == 2))
    check("speed shown", wait_until(lambda: "MB/s" in rows().first.locator(".queue-status").inner_text()), rows().first.locator(".queue-status").inner_text())
    check("progress bar exposes accessible value", rows().first.locator(".queue-bar").get_attribute("role") == "progressbar")
    check("both complete", wait_until(lambda: states() == ["completed", "completed"], 40), str(states()))
    msg = rows().first.locator(".queue-status").inner_text()
    name = rows().first.locator(".queue-status").get_attribute("title") or ""
    check("completed row says saved; tooltip names the file", msg.startswith("Saved") and name.endswith(".mp4"), msg + "|" + name)
    check("saved filename is safe (title had ':')", ":" not in name and "/" not in name, name)
    check("file really exists with the right size", (WORK / "out" / name).exists() and (WORK / "out" / name).stat().st_size == 3_000_000)
    check("temp folder cleaned", list((WORK / "temp").glob("job-*")) == [])
    check("open buttons replace cancel", btn(rows().first, "Open").is_visible() and btn(rows().first, "Folder").is_visible() and not btn(rows().first, "Cancel").is_visible())
    page.screenshot(path=str(SHOTS) + "/7-completed.png")
    btn(rows().first, "Open").click(); btn(rows().first, "Folder").click()
    wait_until(lambda: (WORK / "open.log").exists() and len((WORK / "open.log").read_text().splitlines()) >= 2)
    log = (WORK / "open.log").read_text().splitlines()
    check("open file/folder go through the server", len(log) == 2 and log[0].startswith("file\t") and log[1].startswith("folder\t"), str(log))
    page.click("#queue-clear-finished")
    check("'Clear finished' empties the list", wait_until(lambda: not page.locator("#queue-section").is_visible()))

    # history is its own page
    page.click("#menu-toggle"); page.click("#menu-history-link")
    page.wait_for_selector("#view-history:not([hidden])")
    check("menu opens the History page", not page.locator("#view-home").is_visible() and page.locator("#history-list > li").count() >= 2)
    page.screenshot(path=str(SHOTS) + "/10-history.png")
    page.click("#history-back")
    page.wait_for_selector("#view-home:not([hidden])")
    check("Back returns to the main screen", not page.locator("#view-history").is_visible())

    # cancel stays cancelled (it used to go back to the queue and restart)
    before = outputs()
    analyze("https://media.example/film")
    page.click("#download-button")
    wait_until(lambda: first_state() == "downloading" and first_progress() > 5)
    btn(rows().first, "Cancel").click()
    check("cancel works", wait_until(lambda: first_state() == "cancelled"))
    page.wait_for_timeout(3500)
    check("cancelled download does not restart", first_state() == "cancelled" and rows().count() == 1)
    check("cancel leaves no file and no temp dir", wait_until(lambda: list((WORK / "temp").glob("job-*")) == []) and outputs() == before, str(outputs()))
    btn(rows().first, "Retry").click()
    check("'Retry' starts a new download", wait_until(lambda: first_state() in ("queued", "downloading")))
    check("...which completes", wait_until(lambda: "completed" in states(), 30), str(states()))
    check("second file never overwrote the first", len(outputs()) == len(before) + 1 and name in outputs(), str(outputs()))
    page.click("#queue-clear-finished")

    # failure
    before = outputs()
    analyze("https://media.example/fail")
    page.click("#download-button")
    check("failure reached", wait_until(lambda: "failed" in states()))
    fm = rows().first.locator(".queue-status").inner_text()
    check("failure is explained in plain language", "sign-in" in fm and "Traceback" not in fm, fm)
    check("failure offers retry and leaves nothing behind", btn(rows().first, "Retry").is_visible() and outputs() == before and list((WORK / "temp").glob("job-*")) == [])
    page.screenshot(path=str(SHOTS) + "/8-failed.png")
    btn(rows().first, "Dismiss").click()

    # conversion that FFmpeg cannot do (stub file is not real media)
    analyze("https://media.example/film")
    page.select_option("#output-select", "mkv")
    page.click("#download-button")
    check("conversion failure reached", wait_until(lambda: "failed" in states(), 30))
    fm = rows().first.locator(".queue-status").inner_text()
    check("conversion error is friendly (no tool names/log text)", "couldn't be converted" in fm and "ffmpeg" not in fm.lower(), fm)
    btn(rows().first, "Dismiss").click()

    # a running download survives a reload
    analyze("https://media.example/film")
    page.click("#download-button")
    wait_until(lambda: first_state() == "downloading" and first_progress() > 5)
    page.reload()
    check("running download is picked up after a reload", wait_until(lambda: rows().count() >= 1 and first_state() in ("downloading", "completed")))
    check("resumed download finishes", wait_until(lambda: "completed" in states(), 30))
    page.click("#queue-clear-finished")

    # quick download skips the analysis
    page.fill("#url-input", "https://media.example/film")
    check("'Download now' offered for a single link", page.locator("#quick-button").is_visible())
    page.click("#quick-button")
    check("quick download is queued without analysing", wait_until(lambda: rows().count() >= 1) and not page.locator("#media-card").is_visible())
    wait_until(lambda: "completed" in states(), 30)
    page.click("#queue-clear-finished")

    # hostile title through the whole flow
    analyze("https://media.example/hostile")
    page.click("#download-button")
    check("hostile-title download completes", wait_until(lambda: "completed" in states(), 30))
    hrow = rows().first.locator(".queue-status").inner_text()
    hname = rows().first.locator(".queue-status").get_attribute("title") or ""
    check("hostile title: safe filename, nothing executed", not any(c in hname for c in '<>:"/\\|?*') and page.title() != "PWNED", hname)
    check("hostile title shown as text in the list", rows().first.locator(".queue-title").inner_text().startswith("<img"))

    # mobile
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    mp = m.new_page(); mp.on("pageerror", lambda e: problems.append(f"mobile pageerror: {e}"))
    mp.goto(URL); mp.wait_for_selector("#status[data-state='ok'], #status[data-state='warn']")
    mp.fill("#url-input", "https://media.example/film"); mp.click("#analyze-button")
    mp.wait_for_selector("#media-card:not([hidden])"); mp.wait_for_timeout(300)
    mp.screenshot(path=str(SHOTS) + "/5-mobile.png", full_page=True)
    check("brand on one line (mobile)", mp.evaluate("document.querySelector('.brand').getBoundingClientRect().height") < 30)
    mp.click("#download-button")
    mp.wait_for_selector("#queue-list > li[data-state='completed']", timeout=30000)
    mp.wait_for_timeout(300)
    mp.screenshot(path=str(SHOTS) + "/9-mobile-done.png", full_page=True)
    overflow = mp.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    check("no horizontal scroll on mobile", not overflow)
    b.close()

print("\nbrowser console problems:", json.dumps(problems, indent=1) if problems else "none")
print(f"\n{sum(results.values())}/{len(results)} checks passed")
