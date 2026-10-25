import { api, ApiError } from "./api.js";
import { initJobs, resumeIfRunning } from "./jobs.js";
import { hideMedia, renderMedia } from "./media.js";
import {
  els,
  renderDependencies,
  renderDependencyError,
  setBusy,
  setStatus,
  showNotice,
  syncClearButton,
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

async function start() {
  els.form.addEventListener("submit", analyze);
  els.paste.addEventListener("click", pasteFromClipboard);
  els.clear.addEventListener("click", clearInput);
  els.input.addEventListener("input", () => {
    hideMedia(); // the shown result no longer matches what is typed
    syncClearButton();
  });
  els.openSettings.addEventListener("click", () => {
    els.settings.showModal();
    refreshDependencies();
  });
  els.refreshDependencies.addEventListener("click", refreshDependencies);
  initJobs();
  document.addEventListener("pm:new-download", clearInput);

  try {
    await api.health();
  } catch {
    setStatus("error", "Backend offline");
    showNotice("error", "The local backend isn't responding. Check that the application is still running.");
    return;
  }
  await refreshDependencies();
  await resumeIfRunning();
  els.input.focus();
}

start();
