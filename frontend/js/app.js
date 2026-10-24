import { api, ApiError } from "./api.js";
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
    showNotice(problem === EMPTY_MESSAGE ? "info" : "error", problem);
    els.input.focus();
    return;
  }

  setBusy(true);
  showNotice("busy", "Analyzing media…");
  try {
    // Phase 1: the backend only validates the address. Phase 2 replaces this with
    // /api/media/analyze, which returns title, thumbnail and formats.
    const result = await api.validateUrl(els.input.value);
    showNotice(
      "success",
      `${result.host} passed the safety checks. Reading its media details comes in the next build phase.`,
    );
  } catch (error) {
    showNotice("error", error instanceof ApiError ? error.message : "Something went wrong. Try again.");
  } finally {
    setBusy(false);
  }
}

async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    els.input.value = text.trim();
    syncClearButton();
    els.input.focus();
    showNotice("info", text.trim() ? "Press Analyze to check this link." : "The clipboard is empty.");
  } catch {
    showNotice("error", "The browser blocked clipboard access. Paste with Ctrl+V instead.");
    els.input.focus();
  }
}

function clearInput() {
  els.input.value = "";
  syncClearButton();
  showNotice("info", EMPTY_MESSAGE);
  els.input.focus();
}

async function refreshDependencies() {
  try {
    const deps = await api.dependencies();
    renderDependencies(deps);
    if (deps.ffmpeg.ok) {
      setStatus("ok", `Ready · FFmpeg ${deps.ffmpeg.version}`);
    } else {
      setStatus("warn", "FFmpeg not found");
    }
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
  els.input.addEventListener("input", syncClearButton);
  els.openSettings.addEventListener("click", () => {
    els.settings.showModal();
    refreshDependencies();
  });
  els.refreshDependencies.addEventListener("click", refreshDependencies);

  try {
    await api.health();
  } catch {
    setStatus("error", "Backend offline");
    showNotice("error", "The local backend isn't responding. Check that the application is still running.");
    return;
  }
  await refreshDependencies();
  els.input.focus();
}

start();
