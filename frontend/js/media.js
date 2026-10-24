// Renders normalized analysis results. Everything from the backend is treated as untrusted text:
// values are only ever assigned through textContent / element.value, never as markup.
import { els } from "./ui.js";

const AUDIO_GROUP = "Audio only";
let current = null;

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Unknown";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const two = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
}

export function formatSize(bytes, approximate = false) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "Unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const text = `${unit === 0 ? value : value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`;
  return approximate ? `about ${text}` : text;
}

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

function updateSize() {
  const format = selectedFormat();
  els.size.textContent = format ? formatSize(format.filesize, format.filesize_approximate) : "Unknown";
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
  els.format.onchange = updateSize;

  els.card.hidden = false;
  // Bring the whole card (including the controls) into view without a jarring animation.
  els.card.scrollIntoView({ block: "nearest", behavior: "auto" });
}

export function hideMedia() {
  current = null;
  els.card.hidden = true;
}

/** The format the user picked, for the download step added in the next phase. */
export function getSelection() {
  const format = selectedFormat();
  return current && format ? { url: current.analysis.url, format } : null;
}
