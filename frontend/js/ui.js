// DOM helpers. Text is always assigned with textContent so remote metadata can never inject markup.

const $ = (id) => document.getElementById(id);

export const els = {
  form: $("url-form"),
  input: $("url-input"),
  paste: $("paste-button"),
  clear: $("clear-button"),
  analyze: $("analyze-button"),
  notice: $("notice"),
  noticeText: $("notice-text"),
  status: $("status"),
  statusText: $("status-text"),
  openSettings: $("open-settings"),
  settings: $("settings-dialog"),
  dependencyList: $("dependency-list"),
  refreshDependencies: $("refresh-dependencies"),
  card: $("media-card"),
  thumbImg: $("media-thumb-img"),
  thumbFallback: $("media-thumb-fallback"),
  title: $("media-title"),
  source: $("media-source"),
  duration: $("media-duration"),
  size: $("media-size"),
  quality: $("quality-select"),
  format: $("format-select"),
  download: $("download-button"),
};

/** kind: "info" | "busy" | "success" | "error" */
export function showNotice(kind, text) {
  els.notice.dataset.kind = kind;
  els.noticeText.textContent = text;
}

/** state: "checking" | "ok" | "warn" | "error" */
export function setStatus(state, text) {
  els.status.dataset.state = state;
  els.statusText.textContent = text;
}

export function setBusy(busy) {
  els.analyze.disabled = busy;
  els.analyze.textContent = busy ? "Analyzing…" : "Analyze";
  els.form.setAttribute("aria-busy", String(busy));
}

export function syncClearButton() {
  els.clear.hidden = els.input.value.length === 0;
}

function dependencyItem(name, ok, detail) {
  const item = document.createElement("li");
  item.className = "dependency";
  item.dataset.state = ok ? "ok" : "missing";

  const mark = document.createElement("span");
  mark.className = "dependency-mark";
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = ok ? "✓" : "✕";

  const label = document.createElement("span");
  label.className = "dependency-name";
  label.textContent = `${name}: ${ok ? "ready" : "not available"}`;

  item.append(mark, label);
  if (detail) {
    const extra = document.createElement("span");
    extra.className = "dependency-detail";
    extra.textContent = detail;
    item.append(extra);
  }
  return item;
}

export function renderDependencies(deps) {
  els.dependencyList.replaceChildren(
    dependencyItem("Backend", deps.backend.ok, `Version ${deps.backend.version}`),
    dependencyItem("Python", deps.python.ok, `Version ${deps.python.version}`),
    dependencyItem("FFmpeg", deps.ffmpeg.ok, deps.ffmpeg.ok ? `Version ${deps.ffmpeg.version}` : deps.ffmpeg.message),
    dependencyItem(
      "Media extractor (yt-dlp)",
      deps.extractor.ok,
      deps.extractor.ok ? `Version ${deps.extractor.version ?? "unknown"}` : deps.extractor.message,
    ),
  );
}

export function renderDependencyError(message) {
  els.dependencyList.replaceChildren(dependencyItem("Backend", false, message));
}
