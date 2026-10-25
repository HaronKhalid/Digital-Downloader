// Download lifecycle in the UI: start, poll, cancel, open, retry.
// All text from the server is assigned with textContent.
import { api, ApiError } from "./api.js";
import { formatEta, formatSize, formatSpeed } from "./format.js";
import { getSelection, syncDownloadButton } from "./media.js";
import { state } from "./state.js";
import { els, showNotice } from "./ui.js";

const POLL_MS = 500;
const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const friendly = (error) => (error instanceof ApiError ? error.message : "Something went wrong. Try again.");

function setProgress(percent) {
  const value = Math.max(0, Math.min(100, Number.isFinite(percent) ? percent : 0));
  els.jobBar.style.setProperty("--progress", String(value)); // CSSOM is allowed by our CSP; inline style attributes are not
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
  for (const [name, button] of Object.entries(all)) button.hidden = !visible.includes(name);
}

export function hidePanel() {
  els.panel.hidden = true;
}

function showPanel(title) {
  els.jobTitle.textContent = title || "Download";
  els.panel.hidden = false;
  els.panel.scrollIntoView({ block: "nearest", behavior: "auto" });
}

function render(job) {
  els.panel.dataset.state = job.status;
  els.jobTitle.textContent = job.title || "Download";
  els.jobStage.textContent = job.stage;
  setProgress(job.progress);

  const total = job.total_bytes;
  els.jobDownloaded.textContent =
    job.downloaded_bytes > 0 ? (total ? `${formatSize(job.downloaded_bytes)} of ${formatSize(total)}` : formatSize(job.downloaded_bytes)) : "—";
  els.jobSpeed.textContent = job.status === "downloading" ? formatSpeed(job.speed_bps) : "—";
  els.jobEta.textContent = job.status === "downloading" ? formatEta(job.eta_seconds) : "—";

  switch (job.status) {
    case "queued":
    case "downloading":
      els.jobMessage.textContent = "";
      showButtons(["cancel"]);
      break;
    case "processing":
      els.jobMessage.textContent = "Processing media…";
      showButtons(["cancel"]);
      break;
    case "completed":
      els.jobMessage.textContent = `Download completed. Saved as ${job.filename}`;
      showButtons(["openFile", "openFolder", "another"]);
      document.dispatchEvent(new CustomEvent("pm:job-completed", { detail: job }));
      break;
    case "failed":
      els.jobMessage.textContent = job.error?.message ?? "The download failed.";
      showButtons(["retry", "another"]);
      break;
    case "cancelled":
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
    poll(jobId);
  } catch (error) {
    showNotice("error", friendly(error));
    syncDownloadButton();
  }
}

export function startDownload() {
  const selection = getSelection();
  if (!selection) return;
  begin({ url: selection.url, format_id: selection.format.id, output_format: selection.output });
}

async function cancel() {
  if (!state.activeJobId) return;
  els.jobCancel.disabled = true;
  els.jobStage.textContent = "Cancelling…";
  try {
    await api.cancelJob(state.activeJobId);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 409)) els.jobMessage.textContent = friendly(error);
  }
}

async function open(action) {
  try {
    await api.openJob(state.lastJobId, action);
  } catch (error) {
    els.jobMessage.textContent = friendly(error);
  }
}

/** After a page reload, pick up a download that is still running on the backend. */
export async function resumeIfRunning() {
  try {
    const { jobs } = await api.listJobs();
    const running = jobs.find((j) => !TERMINAL.has(j.status));
    if (!running) return;
    state.activeJobId = running.job_id;
    state.lastJobId = running.job_id;
    showPanel(running.title);
    render(running);
    syncDownloadButton();
    poll(running.job_id);
  } catch {
    /* nothing to resume */
  }
}

export function initJobs() {
  els.download.addEventListener("click", startDownload);
  els.jobCancel.addEventListener("click", cancel);
  els.jobOpenFile.addEventListener("click", () => open("file"));
  els.jobOpenFolder.addEventListener("click", () => open("folder"));
  els.jobRetry.addEventListener("click", () => state.lastRequest && begin(state.lastRequest));
  els.jobAnother.addEventListener("click", () => {
    hidePanel();
    document.dispatchEvent(new CustomEvent("pm:new-download"));
  });
}
