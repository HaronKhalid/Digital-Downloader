// Download lifecycle in the UI: start, poll, cancel, open, retry.
import { api, ApiError } from "./api.js";
import { formatEta, formatSize, formatSpeed } from "./format.js";
import { getCurrentAnalysis, getSelection, syncDownloadButton } from "./media.js";
import { state } from "./state.js";
import { els, showNotice } from "./ui.js";

const POLL_MS = 500;
const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const friendly = (error) => (error instanceof ApiError ? error.message : "Something went wrong. Try again.");

function setProgress(percent) {
  const value = Math.max(0, Math.min(100, Number.isFinite(percent) ? percent : 0));
  els.jobBar.style.setProperty("--progress", `${value}%`);
  els.jobProgress.setAttribute("aria-valuenow", String(Math.floor(value)));
  els.jobPercent.textContent = `${Math.floor(value)}%`;
}

function showButtons(visible) {
  const all = {
    cancel: els.jobCancel,
    openFile: els.jobOpenFile,
    openFolder: els.jobOpenFolder,
    retry: els.jobRetry,
    another: els.jobAnother,
  };
  for (const [name, button] of Object.entries(all)) {
    if (button) button.hidden = !visible.includes(name);
  }
}

export function hidePanel() {
  els.panel.hidden = true;
  if (els.cardEmptyState && (!els.card || els.card.hidden)) {
    els.cardEmptyState.hidden = false;
  }
}

function showPanel(title) {
  if (els.cardEmptyState) els.cardEmptyState.hidden = true;
  if (els.card) els.card.hidden = true;
  els.panel.hidden = false;

  els.jobTitle.textContent = title || "Download";
  if (els.jobHeadTitle) els.jobHeadTitle.textContent = "Downloading...";
  if (els.jobCompleteCheck) els.jobCompleteCheck.hidden = true;
  if (els.jobSaveConfirmation) els.jobSaveConfirmation.hidden = true;
  if (els.jobProgressSection) els.jobProgressSection.hidden = false;

  // Sync thumbnail and specs from analysis
  const analysis = getCurrentAnalysis();
  if (els.jobThumbImg && analysis?.thumbnail) {
    els.jobThumbImg.src = analysis.thumbnail;
    els.jobThumbImg.hidden = false;
    if (els.jobThumbFallback) els.jobThumbFallback.hidden = true;
  } else if (els.jobThumbFallback) {
    if (els.jobThumbImg) els.jobThumbImg.hidden = true;
    els.jobThumbFallback.hidden = false;
  }

  if (els.jobSpecs && els.mediaSpecs) {
    els.jobSpecs.textContent = els.mediaSpecs.textContent;
  }

  els.panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function render(job) {
  els.panel.dataset.state = job.status;
  els.jobTitle.textContent = job.title || "Download";
  els.jobStage.textContent = job.stage;
  setProgress(job.progress);

  const total = job.total_bytes;
  const downloadedText = job.downloaded_bytes > 0
    ? (total ? `${formatSize(job.downloaded_bytes)} / ${formatSize(total)}` : formatSize(job.downloaded_bytes))
    : `Downloading... ${Math.floor(job.progress)}%`;
  
  els.jobDownloaded.textContent = downloadedText;
  els.jobSpeed.textContent = job.status === "downloading" ? formatSpeed(job.speed_bps) : "—";
  els.jobEta.textContent = job.status === "downloading" ? formatEta(job.eta_seconds) : "—";

  switch (job.status) {
    case "queued":
    case "downloading":
      if (els.jobHeadTitle) els.jobHeadTitle.textContent = "Downloading...";
      if (els.jobCompleteCheck) els.jobCompleteCheck.hidden = true;
      if (els.jobSaveConfirmation) els.jobSaveConfirmation.hidden = true;
      if (els.jobProgressSection) els.jobProgressSection.hidden = false;
      els.jobMessage.textContent = "";
      showButtons(["cancel"]);
      break;
    case "processing":
      if (els.jobHeadTitle) els.jobHeadTitle.textContent = "Processing...";
      if (els.jobCompleteCheck) els.jobCompleteCheck.hidden = true;
      if (els.jobSaveConfirmation) els.jobSaveConfirmation.hidden = true;
      if (els.jobProgressSection) els.jobProgressSection.hidden = false;
      els.jobMessage.textContent = "Processing media…";
      showButtons(["cancel"]);
      break;
    case "completed": {
      const completedId = job.job_id ?? job.id;
      state.lastJobId = completedId;
      if (els.jobOpenFile) els.jobOpenFile.dataset.jobId = completedId;
      if (els.jobOpenFolder) els.jobOpenFolder.dataset.jobId = completedId;
      if (els.jobHeadTitle) els.jobHeadTitle.textContent = "Download Complete";
      if (els.jobCompleteCheck) els.jobCompleteCheck.hidden = false;
      if (els.jobSaveConfirmation) els.jobSaveConfirmation.hidden = false;
      if (els.jobSaveText) {
        const outDir = els.outputDirectory?.value?.trim();
        if (outDir) {
          const parts = outDir.split(/[\\/]/).filter(Boolean);
          const sep = outDir.includes("\\") && !outDir.includes("/") ? "\\" : "/";
          const shortName = parts.length > 1 ? parts.slice(-2).join(sep) : (parts[0] || "Downloads");
          els.jobSaveText.textContent = `Saved to ${shortName}`;
        } else {
          els.jobSaveText.textContent = "File saved to your device";
        }
      }
      if (els.jobProgressSection) els.jobProgressSection.hidden = true;
      els.jobMessage.textContent = job.filename ? `Saved as ${job.filename}` : "";
      if (els.jobAnother) els.jobAnother.textContent = "Download another file";
      showButtons(["openFile", "openFolder", "another"]);
      document.dispatchEvent(new CustomEvent("pm:job-completed", { detail: job }));
      break;
    }
    case "failed":
      if (els.jobHeadTitle) els.jobHeadTitle.textContent = "Download Failed";
      if (els.jobCompleteCheck) els.jobCompleteCheck.hidden = true;
      if (els.jobSaveConfirmation) els.jobSaveConfirmation.hidden = true;
      if (els.jobProgressSection) els.jobProgressSection.hidden = true;
      els.jobMessage.textContent = job.error?.message ?? "The download failed.";
      showButtons(["retry", "another"]);
      break;
    case "cancelled":
      if (els.jobHeadTitle) els.jobHeadTitle.textContent = "Download Cancelled";
      if (els.jobCompleteCheck) els.jobCompleteCheck.hidden = true;
      if (els.jobSaveConfirmation) els.jobSaveConfirmation.hidden = true;
      if (els.jobProgressSection) els.jobProgressSection.hidden = true;
      els.jobMessage.textContent = "Download cancelled.";
      showButtons(["retry", "another"]);
      break;
  }
  els.jobCancel.disabled = false;
}

function finish() {
  state.lastJobId = state.activeJobId ?? state.lastJobId;
  state.activeJobId = null;
  syncDownloadButton();
}

function renderLost(message) {
  els.panel.dataset.state = "failed";
  els.jobStage.textContent = "Stopped";
  els.jobMessage.textContent = message;
  if (els.jobProgressSection) els.jobProgressSection.hidden = true;
  showButtons(["retry", "another"]);
}

async function poll(jobId) {
  let failures = 0;
  while (state.activeJobId === jobId) {
    try {
      const job = await api.getJob(jobId);
      failures = 0;
      render(job);
      if (TERMINAL.has(job.status)) {
        finish();
        return;
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        renderLost("This download is no longer known. The application may have been restarted.");
        finish();
        return;
      }
      failures += 1;
      if (failures >= 4) {
        renderLost("Lost contact with the local backend. Check that the application is still running.");
        finish();
        return;
      }
    }
    await sleep(POLL_MS);
  }
}

async function begin(request) {
  if (state.activeJobId) return;
  els.download.disabled = true;
  showNotice("busy", "Starting download…");
  try {
    const { job_id: jobId } = await api.createJob(request);
    state.activeJobId = jobId;
    state.lastJobId = jobId;
    state.lastRequest = request;
    syncDownloadButton();
    els.panel.dataset.state = "queued";
    setProgress(0);
    els.jobStage.textContent = "Waiting to start";
    els.jobMessage.textContent = "";
    els.jobDownloaded.textContent = els.jobSpeed.textContent = els.jobEta.textContent = "—";
    showButtons(["cancel"]);
    showPanel(getSelection()?.format ? document.getElementById("media-title").textContent : "Download");
    showNotice("info", "Download started.");
    document.dispatchEvent(new CustomEvent("pm:job-created", { detail: { jobId } }));
    poll(jobId);
  } catch (error) {
    syncDownloadButton();
    showNotice("error", friendly(error));
  }
}

export function startDownload() {
  const selection = getSelection();
  if (!selection) return;
  const payload = {
    url: selection.url,
    format_id: selection.format.id,
  };
  if (selection.output && typeof selection.output === "string" && selection.output.trim()) {
    payload.output_format = selection.output.trim().toLowerCase();
  }
  begin(payload);
}

export async function cancelDownload() {
  if (!state.activeJobId) return;
  els.jobCancel.disabled = true;
  showNotice("busy", "Stopping download…");
  try {
    await api.cancelJob(state.activeJobId);
  } catch (error) {
    showNotice("error", friendly(error));
  }
}

export async function openFile(evt) {
  const jobId = evt?.currentTarget?.dataset?.jobId || state.activeJobId || state.lastJobId;
  if (!jobId) {
    showNotice("error", "No completed file found to open.");
    return;
  }
  try {
    showNotice("busy", "Opening file…");
    await api.openJob(jobId, "file");
    showNotice("success", "Opened file in default player.");
  } catch (error) {
    showNotice("error", friendly(error));
  }
}

export async function openFolder(evt) {
  if (window.AndroidBridge && typeof window.AndroidBridge.openDownloadsFolder === "function") {
    try {
      window.AndroidBridge.openDownloadsFolder();
      return;
    } catch (_) {}
  }
  const jobId = evt?.currentTarget?.dataset?.jobId || state.activeJobId || state.lastJobId;
  if (!jobId) {
    showNotice("error", "No completed file found to open.");
    return;
  }
  try {
    showNotice("busy", "Opening downloads folder…");
    await api.openJobFolder(jobId);
    showNotice("success", "Opened folder in file manager.");
  } catch (error) {
    showNotice("error", friendly(error));
  }
}

export function retryDownload() {
  if (state.lastRequest) begin(state.lastRequest);
}

export function downloadAnother() {
  hidePanel();
  document.dispatchEvent(new CustomEvent("pm:new-download"));
}

export async function resumeIfRunning() {
  // On the phone the download list already shows everything that is running.
  if (window.AndroidBridge) return;
  try {
    const jobs = await api.listJobs();
    const active = jobs.find((j) => !TERMINAL.has(j.status));
    if (active) {
      const activeId = active.job_id ?? active.id;
      state.activeJobId = activeId;
      state.lastJobId = activeId;
      syncDownloadButton();
      showPanel(active.title);
      render(active);
      poll(activeId);
    }
  } catch {
    /* backend down or initial connection */
  }
}

export function initJobs() {
  els.download.addEventListener("click", startDownload);
  els.jobCancel.addEventListener("click", cancelDownload);
  els.jobOpenFile.addEventListener("click", openFile);
  els.jobOpenFolder.addEventListener("click", openFolder);
  els.jobRetry.addEventListener("click", retryDownload);
  els.jobAnother.addEventListener("click", downloadAnother);
}
