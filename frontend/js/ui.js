// DOM helpers. Text is always assigned with textContent so remote metadata can never inject markup.
import { formatRelativeTime, formatSize } from "./format.js";

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
  themeToggle: $("theme-toggle"),
  themeIconSun: $("theme-icon-sun"),
  themeIconMoon: $("theme-icon-moon"),
  openSettings: $("open-settings"),
  settings: $("settings-dialog"),
  themeSelect: $("theme-select"),
  outputDirectory: $("output-directory-input"),
  saveSettings: $("save-settings-button"),
  settingsMessage: $("settings-save-message"),
  allowedDomains: $("allowed-domains-input"),
  saveDomains: $("save-domains-button"),
  domainsMessage: $("domains-save-message"),
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
  output: $("output-select"),
  download: $("download-button"),
  downloadHint: $("download-hint"),
  panel: $("job-panel"),
  jobTitle: $("job-title"),
  jobStage: $("job-stage"),
  jobProgress: $("job-progress"),
  jobBar: $("job-progress-bar"),
  jobPercent: $("job-percent"),
  jobDownloaded: $("job-downloaded"),
  jobSpeed: $("job-speed"),
  jobEta: $("job-eta"),
  jobMessage: $("job-message"),
  jobCancel: $("job-cancel"),
  jobOpenFile: $("job-open-file"),
  jobOpenFolder: $("job-open-folder"),
  jobRetry: $("job-retry"),
  jobAnother: $("job-another"),
  historyEmpty: $("history-empty"),
  historyList: $("history-list"),
  refreshHistory: $("refresh-history-button"),
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

// ----------------------------------------------------------------- Theme
export function applyTheme(theme) {
  const isSystem = theme === "system";
  const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const activeDark = isSystem ? systemPrefersDark : theme === "dark";

  if (isSystem) {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.dataset.theme = theme;
  }
  localStorage.setItem("pm-theme", theme);
  if (els.themeSelect) els.themeSelect.value = theme;

  if (els.themeIconSun && els.themeIconMoon) {
    els.themeIconSun.hidden = !activeDark;
    els.themeIconMoon.hidden = activeDark;
  }
}

export function initTheme() {
  const saved = localStorage.getItem("pm-theme") || "system";
  applyTheme(saved);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if ((localStorage.getItem("pm-theme") || "system") === "system") {
      applyTheme("system");
    }
  });
}

export function toggleTheme() {
  const current = localStorage.getItem("pm-theme") || "system";
  const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const isDarkNow = current === "dark" || (current === "system" && systemPrefersDark);
  applyTheme(isDarkNow ? "light" : "dark");
}

// ------------------------------------------------------------- Dependencies
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

// ----------------------------------------------------------------- History
export function renderHistory(items, { onOpen, onFolder, onDelete }) {
  if (!items || items.length === 0) {
    els.historyEmpty.hidden = false;
    els.historyList.replaceChildren();
    return;
  }

  els.historyEmpty.hidden = true;
  const fragments = items.map((item) => {
    const li = document.createElement("li");
    li.className = "history-item";
    li.dataset.id = item.id;

    const main = document.createElement("div");
    main.className = "history-main";

    const badge = document.createElement("span");
    badge.className = "format-badge";
    badge.textContent = item.format_label || "FILE";

    const info = document.createElement("div");
    info.className = "history-info";

    const title = document.createElement("h3");
    title.className = "history-title";
    title.textContent = item.title || item.filename || "Untitled";
    title.title = item.title || item.filename || "";

    const meta = document.createElement("p");
    meta.className = "history-meta";

    const parts = [];
    if (item.file_size > 0) parts.push(formatSize(item.file_size));
    const relTime = formatRelativeTime(item.completed_at);
    if (relTime) parts.push(relTime);
    if (item.source) parts.push(item.source);
    meta.textContent = parts.join(" · ");

    if (!item.file_exists) {
      const missing = document.createElement("span");
      missing.className = "missing-badge";
      missing.textContent = "(File missing or moved)";
      meta.appendChild(missing);
    }

    info.append(title, meta);
    main.append(badge, info);

    const actions = document.createElement("div");
    actions.className = "history-actions";

    const openFileBtn = document.createElement("button");
    openFileBtn.type = "button";
    openFileBtn.className = "button small primary";
    openFileBtn.textContent = "Open file";
    openFileBtn.disabled = !item.file_exists;
    openFileBtn.addEventListener("click", () => onOpen(item.id));

    const openFolderBtn = document.createElement("button");
    openFolderBtn.type = "button";
    openFolderBtn.className = "button small quiet";
    openFolderBtn.textContent = "Folder";
    openFolderBtn.disabled = !item.file_exists;
    openFolderBtn.addEventListener("click", () => onFolder(item.id));

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "button small quiet danger";
    deleteBtn.setAttribute("aria-label", "Delete history item");
    deleteBtn.textContent = "✕";
    deleteBtn.addEventListener("click", () => onDelete(item.id));

    actions.append(openFileBtn, openFolderBtn, deleteBtn);
    li.append(main, actions);
    return li;
  });

  els.historyList.replaceChildren(...fragments);
}

// ---------------------------------------------------------------- Settings
export function setSettingsMessage(state, text) {
  els.settingsMessage.dataset.state = state;
  els.settingsMessage.textContent = text;
}

export function setDomainsMessage(state, text) {
  if (!els.domainsMessage) return;
  els.domainsMessage.dataset.state = state;
  els.domainsMessage.textContent = text;
}
