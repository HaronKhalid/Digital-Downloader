import { api, ApiError, getBackendBaseUrl, setBackendBaseUrl } from "./api.js";
import { initJobs, resumeIfRunning, hidePanel } from "./jobs.js";
import { hideMedia, renderMedia } from "./media.js";
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

async function analyze(event) {
  event.preventDefault();
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
  try {
    const text = (await navigator.clipboard.readText()).trim();
    els.input.value = text;
    hideMedia();
    syncClearButton();
    els.input.focus();
    showNotice("info", text ? "Press Analyze to check this link." : "The clipboard is empty.");
  } catch {
    showNotice("error", "The browser blocked clipboard access. Paste with Ctrl+V instead.");
    els.input.focus();
  }
}

function clearInput() {
  els.input.value = "";
  hideMedia();
  syncClearButton();
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
    const message = error instanceof ApiError ? error.message : "Could not check dependencies.";
    renderDependencyError(message);
    setStatus("error", "Backend offline");
  }
}

async function loadHistory() {
  try {
    const res = await api.history(50);
    renderHistory(res.items, {
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

    const cookies = await api.getCookies();
    renderCookiesStatus(cookies);
  } catch {
    setSettingsMessage("error", "Could not load settings.");
  }
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

async function start() {
  initTheme();

  els.form.addEventListener("submit", analyze);
  els.paste.addEventListener("click", pasteFromClipboard);
  els.clear.addEventListener("click", clearInput);
  els.input.addEventListener("input", () => {
    hideMedia();
    syncClearButton();
  });

  if (els.themeToggle) {
    els.themeToggle.addEventListener("click", toggleTheme);
  }
  if (els.themeSelect) {
    els.themeSelect.addEventListener("change", (e) => applyTheme(e.target.value));
  }

  els.openSettings.addEventListener("click", () => {
    els.settings.showModal();
    refreshDependencies();
    loadSettings();
  });
  els.settings.addEventListener("close", () => {
    els.openSettings.focus();
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
  document.addEventListener("pm:new-download", clearInput);
  document.addEventListener("pm:job-completed", () => {
    loadHistory();
  });

  const backendUrlInput = document.getElementById("backend-url-input");
  const saveBackendUrlBtn = document.getElementById("save-backend-url-button");
  const backendUrlMsg = document.getElementById("backend-url-message");

  if (backendUrlInput) {
    backendUrlInput.value = getBackendBaseUrl();
  }
  if (saveBackendUrlBtn && backendUrlInput) {
    saveBackendUrlBtn.addEventListener("click", () => {
      setBackendBaseUrl(backendUrlInput.value);
      if (backendUrlMsg) {
        backendUrlMsg.textContent = "Backend URL saved. Testing connection…";
      }
      api.health()
        .then(() => {
          if (backendUrlMsg) backendUrlMsg.textContent = "Connected successfully!";
          setStatus("ok", "Connected");
          showNotice("success", "Connected to Digital Downloader server.");
        })
        .catch(() => {
          if (backendUrlMsg) backendUrlMsg.textContent = "Could not reach server. Verify address and try again.";
          setStatus("error", "Cannot reach server");
        });
    });
  }

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
