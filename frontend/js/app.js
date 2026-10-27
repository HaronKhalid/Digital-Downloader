import { api, ApiError, isAndroidApp } from "./api.js";
import { initJobs, resumeIfRunning, hidePanel } from "./jobs.js";
import { hideMedia, renderMedia } from "./media.js";
import { initQueue, kickQueue } from "./queue.js";
import {
  applyTheme,
  els,
  initTheme,
  renderDependencies,
  renderDependencyError,
  renderHistory,
  renderCookiesStatus,
  setBusy,
  setCookiesMessage,
  setDomainsMessage,
  setSettingsMessage,
  setStatus,
  showNotice,
  syncClearButton,
  toggleTheme,
} from "./ui.js";

const EMPTY_MESSAGE = "Paste a media URL to begin.";

/** Quick checks before bothering the backend. The backend repeats and enforces all of them. */
function checkLocally(raw) {
  const value = raw.trim();
  if (!value) return EMPTY_MESSAGE;
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return "That doesn't look like a web address. Start it with https://";
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return "Only http:// and https:// links are supported.";
  }
  return null;
}

/** Every http(s) link in the box, separated by spaces or new lines. Duplicates are dropped. */
function extractUrls(raw) {
  const seen = new Set();
  return (raw || "")
    .split(/\s+/)
    .map((part) => part.trim())
    .filter((part) => part && !seen.has(part) && seen.add(part));
}

/** Show "Queue N links" and the quality choice when several links are pasted. */
function syncBatchUi() {
  const count = extractUrls(els.input.value).length;
  const multi = count > 1;
  if (els.batchMode) els.batchMode.hidden = !multi;
  if (!els.analyze.disabled) els.analyze.textContent = multi ? `Queue ${count} links` : "Analyze";
}

async function queueBatch(urls) {
  const bad = urls.find((u) => checkLocally(u));
  if (bad) {
    showNotice("error", `"${bad.slice(0, 60)}" is not a valid link. Start each link with https://`);
    return;
  }
  if (urls.length > 25) {
    showNotice("error", "You can queue up to 25 links at a time.");
    return;
  }
  hideMedia();
  setBusy(true);
  showNotice("busy", `Checking ${urls.length} links…`);
  try {
    const result = await api.batchJobs(urls, els.batchMode?.value || "best");
    const failed = result.items.filter((item) => !item.ok);
    if (result.queued > 0) {
      document.dispatchEvent(new CustomEvent("pm:job-created", { detail: { batch: true } }));
      kickQueue();
    }
    if (failed.length === 0) {
      showNotice("success", `Added ${result.queued} downloads to the queue.`);
      els.input.value = "";
      syncClearButton();
    } else {
      const first = failed[0];
      showNotice(
        result.queued > 0 ? "info" : "error",
        `Queued ${result.queued}, skipped ${failed.length}. ${first.url.slice(0, 40)}: ${first.error}`,
      );
      // keep only the links that failed so the user can fix and retry them
      els.input.value = failed.map((item) => item.url).join(" ");
      syncClearButton();
    }
  } catch (error) {
    showNotice("error", error instanceof ApiError ? error.message : "Something went wrong. Try again.");
  } finally {
    setBusy(false);
    syncBatchUi();
  }
}

async function analyze(event) {
  event.preventDefault();
  const links = extractUrls(els.input.value);
  if (links.length > 1) {
    await queueBatch(links);
    return;
  }
  const url = (els.input.value || "").trim();
  const problem = checkLocally(url);
  if (problem) {
    hideMedia();
    showNotice(problem === EMPTY_MESSAGE ? "info" : "error", problem);
    els.input.focus();
    return;
  }

  hideMedia();
  setBusy(true);
  showNotice("busy", "Analyzing media…");
  try {
    const analysis = await api.analyze(url);
    renderMedia(analysis);
    showNotice("success", "Choose a format and start processing.");
  } catch (error) {
    showNotice("error", error instanceof ApiError ? error.message : "Something went wrong. Try again.");
  } finally {
    setBusy(false);
  }
}

async function pasteFromClipboard() {
  let text = "";
  if (window.AndroidBridge && typeof window.AndroidBridge.getClipboardText === "function") {
    try {
      text = (window.AndroidBridge.getClipboardText() || "").trim();
    } catch (_) {}
  }
  if (!text && navigator.clipboard && typeof navigator.clipboard.readText === "function") {
    try {
      text = (await navigator.clipboard.readText()).trim();
    } catch (_) {}
  }
  if (text) {
    text = text.replace(/[\\/\s]+$/, "").trim().replace(/\s+/g, " ");
    els.input.value = text;
    hideMedia();
    syncClearButton();
    syncBatchUi();
    els.input.focus();
    const count = extractUrls(text).length;
    showNotice("info", count > 1 ? `${count} links pasted. Press Queue to add them all.` : "Link pasted. Press Analyze to inspect.");
  } else {
    showNotice("info", "Clipboard is empty or access was not granted.");
    els.input.focus();
  }
}

function clearInput() {
  els.input.value = "";
  hideMedia();
  syncClearButton();
  syncBatchUi();
  showNotice("info", EMPTY_MESSAGE);
  els.input.focus();
}

async function refreshDependencies() {
  try {
    const deps = await api.dependencies();
    renderDependencies(deps);
    if (!deps.ffmpeg.ok) setStatus("warn", "FFmpeg not found");
    else if (!deps.extractor.ok) setStatus("warn", "Media extractor not installed");
    else setStatus("ok", `Ready · FFmpeg ${deps.ffmpeg.version.split("-")[0]}`);
  } catch (error) {
    setStatus("error", isAndroidApp() ? "Download engine unavailable" : "Backend offline");
  }
}

async function loadHistory() {
  try {
    const res = await api.history(50);
    const items = Array.isArray(res) ? res : (res?.items || []);
    renderHistory(items, {
      onOpen: async (id) => {
        try {
          await api.openHistory(id, "file");
        } catch (err) {
          showNotice("error", err instanceof ApiError ? err.message : "Could not open file.");
        }
      },
      onFolder: async (id) => {
        if (window.AndroidBridge && typeof window.AndroidBridge.openDownloadsFolder === "function") {
          try {
            window.AndroidBridge.openDownloadsFolder();
            return;
          } catch (_) {}
        }
        try {
          await api.openHistory(id, "folder");
        } catch (err) {
          showNotice("error", err instanceof ApiError ? err.message : "Could not open folder.");
        }
      },
      onDelete: async (id) => {
        try {
          await api.deleteHistory(id);
          await loadHistory();
        } catch (err) {
          showNotice("error", err instanceof ApiError ? err.message : "Could not delete history item.");
        }
      },
    });
  } catch {
    // If backend isn't ready yet, history will be tried again on connection
  }
}

async function loadSettings() {
  try {
    const data = await api.settings();
    if (els.outputDirectory) {
      els.outputDirectory.value = data.output_directory;
    }
    if (els.universalMode) {
      els.universalMode.checked = Boolean(data.universal_mode);
      if (els.allowedDomainsField) {
        els.allowedDomainsField.style.opacity = data.universal_mode ? "0.4" : "1";
      }
    }
    if (els.allowedDomains && data.allowed_source_domains) {
      els.allowedDomains.value = data.allowed_source_domains.join(", ");
    }
    setSettingsMessage("", "");
    setDomainsMessage("", "");
    if (isAndroidApp()) setupAndroidSettings(data);

    const cookies = await api.getCookies();
    renderCookiesStatus(cookies);
  } catch {
    setSettingsMessage("error", "Could not load settings.");
  }
}

let androidSettingsReady = false;

function setupAndroidSettings(data) {
  // On the phone, files always go to Downloads/DigitalDownloader: show it, but don't let it be edited.
  if (els.outputDirectory) els.outputDirectory.readOnly = true;
  document.getElementById("save-settings-button")?.setAttribute("hidden", "");
  const box = document.getElementById("android-share-settings");
  const mode = document.getElementById("share-mode-select");
  const quality = document.getElementById("share-quality-select");
  const message = document.getElementById("share-settings-message");
  if (!box || !mode || !quality) return;
  box.hidden = false;
  mode.value = data.share_mode || "background";
  quality.value = data.share_quality || "best";
  if (androidSettingsReady) return;
  androidSettingsReady = true;
  const save = async () => {
    try {
      await api.updateSettings({ share_mode: mode.value, share_quality: quality.value });
      if (message) message.textContent = "Saved.";
    } catch (err) {
      if (message) message.textContent = err instanceof ApiError ? err.message : "Could not save.";
    }
  };
  mode.addEventListener("change", save);
  quality.addEventListener("change", save);
}

async function saveSettings(e) {
  if (e) e.preventDefault();
  const dir = els.outputDirectory.value.trim();
  if (!dir) {
    setSettingsMessage("error", "Please enter a valid folder path.");
    return;
  }
  setSettingsMessage("", "Saving…");
  try {
    const updated = await api.updateSettings({ output_directory: dir });
    els.outputDirectory.value = updated.output_directory;
    setSettingsMessage("ok", "Download folder updated successfully.");
  } catch (err) {
    setSettingsMessage("error", err instanceof ApiError ? err.message : "Could not save folder path.");
  }
}

async function saveDomains(e) {
  if (e) e.preventDefault();
  if (!els.allowedDomains) return;
  const raw = els.allowedDomains.value.trim();
  const domains = raw
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  if (domains.length === 0) {
    setDomainsMessage("error", "Please enter at least one allowed domain.");
    return;
  }
  setDomainsMessage("", "Saving…");
  try {
    const updated = await api.updateSettings({ allowed_source_domains: domains });
    els.allowedDomains.value = updated.allowed_source_domains.join(", ");
    setDomainsMessage("ok", "Allowed domains updated successfully.");
  } catch (err) {
    setDomainsMessage("error", err instanceof ApiError ? err.message : "Could not save allowed domains.");
  }
}

function openMenu() {
  if (!els.menuDrawer) return;
  els.menuDrawer.hidden = false;
  if (els.menuBackdrop) els.menuBackdrop.hidden = false;
  requestAnimationFrame(() => {
    els.menuDrawer.classList.add("open");
    if (els.menuBackdrop) els.menuBackdrop.classList.add("open");
  });
}

function closeMenu() {
  if (!els.menuDrawer) return;
  els.menuDrawer.classList.remove("open");
  if (els.menuBackdrop) els.menuBackdrop.classList.remove("open");
  setTimeout(() => {
    els.menuDrawer.hidden = true;
    if (els.menuBackdrop) els.menuBackdrop.hidden = true;
  }, 260);
}

function setExtractorMessage(kind, text) {
  if (!els.extractorMessage) return;
  els.extractorMessage.textContent = text;
  els.extractorMessage.dataset.kind = kind;
}

async function checkExtractor() {
  els.extractorCheck.disabled = true;
  els.extractorUpdate.hidden = true;
  setExtractorMessage("", "Checking for updates…");
  try {
    const info = await api.checkExtractorUpdate();
    if (!info.supported) {
      setExtractorMessage("error", "In-app updates are not available on this system.");
    } else if (info.update_available) {
      els.extractorText.textContent = `Installed: ${info.current || "unknown"} · Available: ${info.latest}`;
      els.extractorUpdate.hidden = false;
      setExtractorMessage("", "A newer version is available.");
    } else {
      els.extractorText.textContent = `Installed: ${info.current || "unknown"}`;
      setExtractorMessage("ok", "You have the latest version.");
    }
  } catch (error) {
    setExtractorMessage("error", error instanceof ApiError ? error.message : "Could not check for updates.");
  } finally {
    els.extractorCheck.disabled = false;
  }
}

async function installExtractorUpdate() {
  els.extractorUpdate.disabled = true;
  els.extractorCheck.disabled = true;
  setExtractorMessage("", "Downloading and verifying the update…");
  try {
    const result = await api.updateExtractor();
    els.extractorUpdate.hidden = true;
    els.extractorText.textContent = `Installed: ${result.installed}`;
    setExtractorMessage("ok", "Updated. New downloads will use the new version.");
    refreshDependencies();
  } catch (error) {
    setExtractorMessage("error", error instanceof ApiError ? error.message : "The update failed.");
  } finally {
    els.extractorUpdate.disabled = false;
    els.extractorCheck.disabled = false;
  }
}

function initExtractorUpdate() {
  if (!els.extractorCheck || !els.extractorUpdate) return;
  els.extractorCheck.addEventListener("click", checkExtractor);
  els.extractorUpdate.addEventListener("click", installExtractorUpdate);
}

async function start() {
  initTheme();

  els.form.addEventListener("submit", analyze);
  els.paste.addEventListener("click", pasteFromClipboard);
  els.clear.addEventListener("click", clearInput);
  els.input.addEventListener("input", () => {
    hideMedia();
    syncClearButton();
    syncBatchUi();
  });
  // A single-line input would glue pasted lines together; turn line breaks into spaces first.
  els.input.addEventListener("paste", (event) => {
    const text = event.clipboardData?.getData("text");
    if (text && /[\r\n]/.test(text)) {
      event.preventDefault();
      const cleaned = text.trim().replace(/\s+/g, " ");
      els.input.setRangeText(cleaned, els.input.selectionStart, els.input.selectionEnd, "end");
      els.input.dispatchEvent(new Event("input"));
    }
  });

  if (els.menuToggle) {
    els.menuToggle.addEventListener("click", openMenu);
  }
  if (els.menuClose) {
    els.menuClose.addEventListener("click", closeMenu);
  }
  if (els.menuBackdrop) {
    els.menuBackdrop.addEventListener("click", closeMenu);
  }
  if (els.menuHistoryLink) {
    els.menuHistoryLink.addEventListener("click", () => {
      closeMenu();
      const historySec = document.getElementById("history-section") || els.historyList;
      if (historySec) {
        historySec.scrollIntoView({ behavior: "smooth" });
      }
    });
  }

  if (els.themeToggle) {
    els.themeToggle.addEventListener("click", toggleTheme);
  }
  if (els.themeSelect) {
    els.themeSelect.addEventListener("change", (e) => applyTheme(e.target.value));
  }

  if (els.openSettings) {
    els.openSettings.addEventListener("click", () => {
      closeMenu();
      els.settings.showModal();
      refreshDependencies();
      loadSettings();
    });
  }
  els.settings.addEventListener("close", () => {
    if (els.menuToggle) els.menuToggle.focus();
  });

  els.refreshDependencies.addEventListener("click", refreshDependencies);
  if (els.saveSettings) {
    els.saveSettings.addEventListener("click", saveSettings);
  }
  if (els.outputDirectory) {
    els.outputDirectory.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        saveSettings();
      }
    });
  }
  if (els.saveDomains) {
    els.saveDomains.addEventListener("click", saveDomains);
  }
  if (els.allowedDomains) {
    els.allowedDomains.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        saveDomains();
      }
    });
  }

  if (els.refreshHistory) {
    els.refreshHistory.addEventListener("click", loadHistory);
  }

  if (els.closeMediaCard) {
    els.closeMediaCard.addEventListener("click", () => {
      hideMedia();
    });
  }

  if (els.closeJobPanel) {
    els.closeJobPanel.addEventListener("click", () => {
      hidePanel();
    });
  }

  if (els.universalMode) {
    els.universalMode.addEventListener("change", async (e) => {
      const enabled = e.target.checked;
      setDomainsMessage("", "Updating mode…");
      try {
        const updated = await api.updateSettings({ universal_mode: enabled });
        if (els.allowedDomains) {
          els.allowedDomains.value = updated.allowed_source_domains.join(", ");
        }
        if (els.allowedDomainsField) {
          els.allowedDomainsField.style.opacity = enabled ? "0.4" : "1";
        }
        setDomainsMessage("ok", enabled ? "Universal Mode active (Seal style: all sites allowed)." : "Curated allowed sites active.");
      } catch (err) {
        setDomainsMessage("error", err instanceof ApiError ? err.message : "Failed to update mode.");
      }
    });
  }

  if (els.cookiesFileInput) {
    els.cookiesFileInput.addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      try {
        setCookiesMessage("", "Uploading cookies…");
        const text = await file.text();
        const updated = await api.updateCookies(text);
        renderCookiesStatus(updated);
        setCookiesMessage("ok", "Cookies imported successfully.");
      } catch (err) {
        setCookiesMessage("error", err instanceof ApiError ? err.message : "Failed to import cookies.");
      } finally {
        e.target.value = "";
      }
    });
  }

  if (els.pasteCookiesBtn) {
    els.pasteCookiesBtn.addEventListener("click", () => {
      els.cookiesPasteBox.hidden = !els.cookiesPasteBox.hidden;
      if (!els.cookiesPasteBox.hidden && els.cookiesTextarea) els.cookiesTextarea.focus();
    });
  }
  if (els.cancelCookiesTextBtn) {
    els.cancelCookiesTextBtn.addEventListener("click", () => {
      els.cookiesPasteBox.hidden = true;
      if (els.cookiesTextarea) els.cookiesTextarea.value = "";
    });
  }
  if (els.saveCookiesTextBtn) {
    els.saveCookiesTextBtn.addEventListener("click", async () => {
      const text = els.cookiesTextarea?.value.trim();
      if (!text) {
        setCookiesMessage("error", "Please paste valid Netscape cookie content.");
        return;
      }
      try {
        setCookiesMessage("", "Saving cookies…");
        const updated = await api.updateCookies(text);
        renderCookiesStatus(updated);
        els.cookiesPasteBox.hidden = true;
        if (els.cookiesTextarea) els.cookiesTextarea.value = "";
        setCookiesMessage("ok", "Cookies saved successfully.");
      } catch (err) {
        setCookiesMessage("error", err instanceof ApiError ? err.message : "Failed to save cookies.");
      }
    });
  }
  if (els.clearCookiesBtn) {
    els.clearCookiesBtn.addEventListener("click", async () => {
      try {
        setCookiesMessage("", "Removing cookies…");
        const updated = await api.deleteCookies();
        renderCookiesStatus(updated);
        setCookiesMessage("ok", "Cookies removed.");
      } catch (err) {
        setCookiesMessage("error", err instanceof ApiError ? err.message : "Failed to remove cookies.");
      }
    });
  }

  document.querySelectorAll(".platform-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const text = chip.textContent.trim();
      els.input.focus();
      showNotice("info", `Paste any ${text} video or post link above.`);
    });
  });

  initJobs();
  initQueue();
  initExtractorUpdate();
  document.addEventListener("pm:new-download", clearInput);
  document.addEventListener("pm:job-completed", () => {
    loadHistory();
  });

  // Handle shared URLs from Android Share Intent or external shortcuts
  window.handleSharedUrl = (sharedUrl) => {
    if (!sharedUrl || typeof sharedUrl !== "string") return;
    const clean = sharedUrl.trim();
    if (!clean) return;
    els.input.value = clean;
    syncClearButton();
    if (window.AndroidBridge?.vibrate) {
      window.AndroidBridge.vibrate();
    }
    analyze(new Event("submit"));
  };

  // Check on startup if Android bridge has a shared URL waiting
  if (window.AndroidBridge?.getSharedUrl) {
    try {
      const pending = window.AndroidBridge.getSharedUrl();
      if (pending) {
        window.handleSharedUrl(pending);
      }
    } catch (_) {}
  }

  try {
    await api.health();
  } catch {
    setStatus("error", "Backend offline");
    showNotice("error", "The backend isn't responding. Check that the server is running.");
    return;
  }

  await refreshDependencies();
  await loadHistory();
  await resumeIfRunning();
  els.input.focus();
}

start();
