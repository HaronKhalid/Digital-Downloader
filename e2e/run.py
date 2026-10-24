from playwright.sync_api import sync_playwright
import json
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
    page.screenshot(path="e2e/shots/1-empty.png")
    check("status leaves 'checking'", page.locator("#status").get_attribute("data-state") in ("ok", "warn"))
    check("input focused on load", page.evaluate("document.activeElement.id") == "url-input")
    check("card hidden initially", not page.locator("#media-card").is_visible())

    # happy path, submitted with the keyboard
    page.fill("#url-input", "https://media.example/film")
    check("Clear button appears", page.locator("#clear-button").is_visible())
    page.press("#url-input", "Enter")
    page.wait_for_selector("#media-card:not([hidden])")
    page.wait_for_timeout(300)
    page.screenshot(path="e2e/shots/2-card.png")
    bottom = page.evaluate("document.querySelector('#download-button').getBoundingClientRect().bottom")
    check("download controls visible without manual scroll", bottom <= 800, str(bottom))
    check("title rendered", page.inner_text("#media-title").startswith("Prelinger Archives"))
    check("duration formatted h:mm:ss", page.inner_text("#media-duration") == "1:02:05", page.inner_text("#media-duration"))
    check("thumbnail visible", page.locator("#media-thumb-img").is_visible())
    check("quality options", page.locator("#quality-select option").all_inner_texts() == ["1080p", "720p60", "480p", "Audio only"], str(page.locator("#quality-select option").all_inner_texts()))
    check("format options for 1080p", page.locator("#format-select option").all_inner_texts() == ["MP4", "WEBM (no audio)"], str(page.locator("#format-select option").all_inner_texts()))
    check("size shown", page.inner_text("#media-size") == "393 MB", page.inner_text("#media-size"))
    page.select_option("#format-select", "b")
    check("approx size", page.inner_text("#media-size") == "about 219 MB", page.inner_text("#media-size"))
    page.select_option("#quality-select", "480p")
    check("unknown size", page.inner_text("#media-size") == "Unknown")
    page.select_option("#quality-select", "Audio only")
    check("audio formats", page.locator("#format-select option").all_inner_texts() == ["M4A", "MP3"])
    check("download disabled w/ explanation", page.locator("#download-button").is_disabled() and "next build phase" in page.inner_text("#download-hint"))

    # editing the URL invalidates the shown result
    page.fill("#url-input", "https://media.example/film2")
    check("card hides when URL edited", not page.locator("#media-card").is_visible())

    # hostile metadata
    page.fill("#url-input", "https://media.example/hostile"); page.click("#analyze-button")
    page.wait_for_selector("#media-card:not([hidden])"); page.wait_for_timeout(300)
    check("hostile title shown as literal text", page.inner_text("#media-title").startswith("<img src=x onerror="))
    check("no injected elements", page.locator("#media-title *").count() == 0)
    check("no script executed", page.title() == "Personal Media" and dialogs == [], page.title())

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
    page.screenshot(path="e2e/shots/3-error.png")

    # empty submit + clear
    page.fill("#url-input", ""); page.click("#analyze-button")
    check("empty prompt", "Paste a media URL" in page.inner_text("#notice"))
    page.fill("#url-input", "x"); page.click("#clear-button")
    check("clear empties + refocuses", page.input_value("#url-input") == "" and page.evaluate("document.activeElement.id") == "url-input")

    # settings dialog
    page.click("#open-settings"); page.wait_for_selector("#dependency-list .dependency[data-state]")
    page.wait_for_timeout(300)
    page.screenshot(path="e2e/shots/4-settings.png")
    deps = page.locator("#dependency-list").inner_text()
    check("dependencies listed", all(k in deps for k in ("Backend", "Python", "FFmpeg", "Media extractor")), deps)
    page.keyboard.press("Escape")
    check("Escape closes dialog", not page.locator("#settings-dialog").is_visible())

    # mobile
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    mp = m.new_page(); mp.on("pageerror", lambda e: problems.append(f"mobile pageerror: {e}"))
    mp.goto(URL); mp.wait_for_selector("#status[data-state='ok'], #status[data-state='warn']")
    mp.fill("#url-input", "https://media.example/film"); mp.click("#analyze-button")
    mp.wait_for_selector("#media-card:not([hidden])"); mp.wait_for_timeout(300)
    mp.screenshot(path="e2e/shots/5-mobile.png", full_page=True)
    check("brand on one line (mobile)", mp.evaluate("document.querySelector('.brand').getBoundingClientRect().height") < 30)
    overflow = mp.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    check("no horizontal scroll on mobile", not overflow)
    b.close()

print("\nbrowser console problems:", json.dumps(problems, indent=1) if problems else "none")
print(f"\n{sum(results.values())}/{len(results)} checks passed")
