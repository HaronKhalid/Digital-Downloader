import { api, ApiError } from "./api.js";
import { initJobs, resumeIfRunning } from "./jobs.js";
import { hideMedia, renderMedia } from "./media.js";
import {
  applyTheme,
  els,
  initTheme,
  renderDependencies,
  renderDependencyError,
  renderHistory,
  setBusy,
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
  const problem = checkLocally(els.input.value);
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
    const analysis = await api.analyze(els.input.value);
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
    setSettingsMessage("", "");
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
    const updated = await api.updateSettings(dir);
    els.outputDirectory.value = updated.output_directory;
    setSettingsMessage("ok", "Download folder updated successfully.");
  } catch (err) {
    setSettingsMessage("error", err instanceof ApiError ? err.message : "Could not save folder path.");
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

  if (els.refreshHistory) {
    els.refreshHistory.addEventListener("click", loadHistory);
  }

  initJobs();
  document.addEventListener("pm:new-download", clearInput);
  document.addEventListener("pm:job-completed", () => {
    loadHistory();
  });

  try {
    await api.health();
  } catch {
    setStatus("error", "Backend offline");
    showNotice("error", "The local backend isn't responding. Check that the application is still running.");
    return;
  }

  await refreshDependencies();
  await loadHistory();
  await resumeIfRunning();
  els.input.focus();
}

start();
