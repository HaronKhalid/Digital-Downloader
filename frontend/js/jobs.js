// Starting a download. Progress, cancel, retry and open all live in the Downloads list (queue.js),
// so any number of downloads can run at once and none of them ever disappears.
import { api, ApiError } from "./api.js";
import { getSelection, hideMedia, syncDownloadButton } from "./media.js";
import { els, showNotice, syncClearButton } from "./ui.js";

const friendly = (error) => (error instanceof ApiError ? error.message : "Something went wrong. Try again.");

export async function startDownload() {
  const selection = getSelection();
  if (!selection || els.download.disabled) return;
  const payload = { url: selection.url, format_id: selection.format.id };
  if (selection.output && typeof selection.output === "string" && selection.output.trim()) {
    payload.output_format = selection.output.trim().toLowerCase();
  }
  els.download.disabled = true;
  showNotice("busy", "Adding to your downloads…");
  try {
    await api.createJob(payload);
    // Back to a clean screen: the new download shows up in the list and the next link can be pasted straight away.
    hideMedia();
    els.input.value = "";
    syncClearButton();
    showNotice("success", "Added to your downloads. You can paste another link.");
    document.dispatchEvent(new CustomEvent("pm:job-created"));
    els.queueSection?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } catch (error) {
    syncDownloadButton();
    showNotice("error", friendly(error));
  }
}

export function initJobs() {
  els.download.addEventListener("click", startDownload);
}
