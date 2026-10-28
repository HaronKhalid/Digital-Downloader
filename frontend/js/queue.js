// Live list of all downloads (queued, running, finished) with cancel / retry / open.
// Rows are updated in place (keyed by job id) so buttons keep focus while progress changes.
// All text is assigned with textContent; remote titles can never inject markup.
import { api, ApiError } from "./api.js";
import { state } from "./state.js";
import { formatEta, formatSize, formatSpeed } from "./format.js";
import { els, showNotice } from "./ui.js";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const ACTIVE_POLL_MS = 1000;
const dismissed = new Set();
const rows = new Map(); // job id -> { li, refs }
let timer = null;
let idleChecks = 0;

const friendly = (error) => (error instanceof ApiError ? error.message : "Something went wrong. Try again.");

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, className, onClick) {
  const b = make("button", `button small ${className}`, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function statusText(job) {
  switch (job.status) {
    case "queued":
      return "Waiting in queue";
    case "downloading": {
      const parts = [`${Math.floor(job.progress)}%`];
      if (job.speed_bps) parts.push(formatSpeed(job.speed_bps));
      if (job.eta_seconds) parts.push(`${formatEta(job.eta_seconds)} left`);
      return parts.join(" · ");
    }
    case "processing":
      return "Processing…";
    case "completed":
      return job.file_size ? `Completed · ${formatSize(job.file_size)}` : "Completed";
    case "failed":
      return job.error?.message || "The download failed.";
    case "cancelled":
      return "Cancelled";
    default:
      return job.status;
  }
}

function createRow(job) {
  const li = make("li", "queue-item");
  const main = make("div", "queue-main");
  const title = make("p", "queue-title");
  const status = make("p", "queue-status");
  const bar = make("div", "queue-bar");
  bar.setAttribute("role", "progressbar");
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  const fill = make("div", "queue-bar-fill");
  bar.append(fill);
  main.append(title, status, bar);

  const actions = make("div", "queue-actions");
  const cancel = button("Cancel", "quiet", async () => {
    cancel.disabled = true;
    try {
      await api.cancelJob(job.job_id);
    } catch (error) {
      showNotice("error", friendly(error));
    }
    kickQueue();
  });
  const retry = button("Retry", "primary", async () => {
    retry.disabled = true;
    try {
      await api.retryJob(job.job_id);
      dismissed.add(job.job_id);
      showNotice("info", "Download restarted.");
    } catch (error) {
      retry.disabled = false;
      showNotice("error", friendly(error));
    }
    kickQueue();
  });
  const open = button("Open", "secondary", async () => {
    try {
      await api.openJob(job.job_id, "file");
    } catch (error) {
      showNotice("error", friendly(error));
    }
  });
  const dismiss = button("Dismiss", "quiet", () => {
    dismissed.add(job.job_id);
    refreshQueue();
  });
  actions.append(cancel, retry, open, dismiss);
  li.append(main, actions);
  return { li, refs: { title, status, bar, fill, cancel, retry, open, dismiss } };
}

function updateRow({ li, refs }, job) {
  li.dataset.state = job.status;
  refs.title.textContent = job.title || "Download";
  refs.title.title = job.title || "";
  refs.status.textContent = statusText(job);
  const value = Math.max(0, Math.min(100, Number.isFinite(job.progress) ? job.progress : 0));
  refs.fill.style.setProperty("--progress", `${value}%`);
  refs.bar.setAttribute("aria-valuenow", String(Math.floor(value)));
  refs.bar.setAttribute("aria-label", refs.title.textContent);
  refs.bar.hidden = TERMINAL.has(job.status);
  const active = !TERMINAL.has(job.status);
  refs.cancel.hidden = !active;
  refs.retry.hidden = !(job.status === "failed" || job.status === "cancelled");
  refs.open.hidden = job.status !== "completed";
  refs.dismiss.hidden = active;
}

const announced = new Set();
let firstRender = true;

export function renderQueue(jobs) {
  // Tell the rest of the page when a download finished (so "recent downloads" refreshes),
  // but not for downloads that were already finished when the page opened.
  for (const job of jobs) {
    if (job.status === "completed" && !announced.has(job.job_id)) {
      announced.add(job.job_id);
      if (!firstRender) document.dispatchEvent(new CustomEvent("pm:job-completed"));
    }
  }
  firstRender = false;
  // The download you are watching in the big card is not repeated in the list below.
  const watchedId = els.panel && !els.panel.hidden ? state.lastJobId : null;
  // Finished downloads live in "Download History"; this list is only for work in progress or needing attention.
  const visible = jobs.filter(
    (job) => job.status !== "completed" && !dismissed.has(job.job_id) && job.job_id !== watchedId,
  );
  els.queueSection.hidden = visible.length === 0;
  const seen = new Set();
  let previous = null;
  for (const job of visible) {
    seen.add(job.job_id);
    let row = rows.get(job.job_id);
    if (!row) {
      row = createRow(job);
      rows.set(job.job_id, row);
    }
    updateRow(row, job);
    // keep the DOM order identical to the server order without recreating nodes
    const expectedNext = previous ? previous.nextSibling : els.queueList.firstChild;
    if (row.li !== expectedNext) els.queueList.insertBefore(row.li, expectedNext);
    previous = row.li;
  }
  for (const [id, row] of rows) {
    if (!seen.has(id)) {
      row.li.remove();
      rows.delete(id);
    }
  }
  return visible.some((job) => !TERMINAL.has(job.status));
}

export async function refreshQueue() {
  let hasActive = false;
  try {
    const jobs = await api.listJobs();
    const list = Array.isArray(jobs) ? jobs : jobs?.jobs || [];
    hasActive = renderQueue(list);
  } catch {
    return false; // backend offline or standalone mode: stay quiet, try again on the next kick
  }
  return hasActive;
}

/** Start (or restart) polling. Polls quickly while anything is active, then stops. */
export function kickQueue() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(async () => {
    timer = null;
    const active = await refreshQueue();
    if (active) {
      idleChecks = 0;
      kickQueue();
    } else if (idleChecks < 3) {
      // A restored queue is re-created in the background after startup, so look a few more times.
      idleChecks += 1;
      timer = setTimeout(kickQueue, 3000);
    }
  }, 0);
}

export function clearFinished() {
  for (const [id, row] of rows) {
    if (row.li.dataset.state && TERMINAL.has(row.li.dataset.state)) dismissed.add(id);
  }
  refreshQueue();
}

export function initQueue() {
  if (!els.queueSection || !els.queueList) return;
  els.queueClear?.addEventListener("click", clearFinished);
  // Coming back to the app (for example after sharing links to it) shows new downloads straight away.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      idleChecks = 0;
      kickQueue();
    }
  });
  document.addEventListener("pm:job-created", () => {
    idleChecks = 0;
    kickQueue();
  });
  kickQueue();
}
