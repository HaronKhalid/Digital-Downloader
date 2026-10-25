// Renders normalized analysis results. Everything from the backend is treated as untrusted text:
// values are only ever assigned through textContent / element.value, never as markup.
import { formatDuration, formatSize } from "./format.js";
import { state } from "./state.js";
import { els } from "./ui.js";

const VIDEO_OUTPUTS = ["mp4", "mkv", "webm"];
const AUDIO_OUTPUTS = ["mp3", "m4a", "opus"];

const AUDIO_GROUP = "Audio only";
let current = null;

function groupKey(format) {
  return format.type === "audio" ? AUDIO_GROUP : format.resolution ?? "Original file";
}

function groupFormats(formats) {
  const groups = new Map();
  for (const format of formats) {
    const key = groupKey(format);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(format);
  }
  return groups;
}

function option(value, text) {
  const el = document.createElement("option");
  el.value = value;
  el.textContent = text;
  return el;
}

function formatOptionText(format, duplicates) {
  let text = format.container.toUpperCase();
  if (format.type === "video" && !format.has_audio) text += " (no audio)";
  if (duplicates) text += ` [${format.id}]`;
  return text;
}

function fillFormats() {
  const group = current.groups.get(els.quality.value) ?? [];
  const labels = group.map((f) => formatOptionText(f, false));
  els.format.replaceChildren(
    ...group.map((f, i) => option(f.id, formatOptionText(f, labels.filter((l) => l === labels[i]).length > 1))),
  );
  updateSize();
}

function selectedFormat() {
  return current?.analysis.formats.find((f) => f.id === els.format.value) ?? null;
}

function fillOutputs() {
  const format = selectedFormat();
  const choices = format?.type === "audio" ? AUDIO_OUTPUTS : VIDEO_OUTPUTS;
  els.output.replaceChildren(
    option("", "Same as source"),
    ...choices.filter((c) => c !== format?.container).map((c) => option(c, c.toUpperCase())),
  );
}

function updateSize() {
  const format = selectedFormat();
  els.size.textContent = format ? formatSize(format.filesize, format.filesize_approximate) : "Unknown";
  fillOutputs();
}

/** The Download button is only usable when a result is shown and no download is already running. */
export function syncDownloadButton() {
  const busy = state.activeJobId !== null;
  els.download.disabled = busy || selectedFormat() === null;
  els.downloadHint.textContent = busy ? "A download is already running." : "Saved to your PersonalMedia folder.";
}

export function renderMedia(analysis) {
  const groups = groupFormats(analysis.formats);
  current = { analysis, groups };

  els.title.textContent = analysis.title;
  els.source.textContent = analysis.source_label;
  els.duration.textContent = formatDuration(analysis.duration);

  if (typeof analysis.thumbnail === "string" && analysis.thumbnail.startsWith("data:image/")) {
    els.thumbImg.src = analysis.thumbnail;
    els.thumbImg.hidden = false;
    els.thumbFallback.hidden = true;
  } else {
    els.thumbImg.removeAttribute("src");
    els.thumbImg.hidden = true;
    els.thumbFallback.hidden = false;
    els.thumbFallback.textContent = analysis.formats[0]?.type === "audio" ? "Audio" : "Video";
  }

  els.quality.replaceChildren(...[...groups.keys()].map((key) => option(key, key)));
  fillFormats();
  els.quality.onchange = fillFormats;
  els.format.onchange = () => {
    updateSize();
    syncDownloadButton();
  };

  syncDownloadButton();
  els.card.hidden = false;
  // Bring the whole card (including the controls) into view without a jarring animation.
  els.card.scrollIntoView({ block: "nearest", behavior: "auto" });
}

export function hideMedia() {
  current = null;
  els.card.hidden = true;
}

/** What the user picked: the analyzed URL, the format, and the optional "Save as" container. */
export function getSelection() {
  const format = selectedFormat();
  return current && format ? { url: current.analysis.url, format, output: els.output.value || null } : null;
}
