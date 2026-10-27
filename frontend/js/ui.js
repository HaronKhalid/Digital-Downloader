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
  themeModeText: $("theme-mode-text"),
  menuToggle: $("menu-toggle"),
  menuDrawer: $("menu-drawer"),
  menuBackdrop: $("menu-backdrop"),
  menuClose: $("menu-close"),
  menuHistoryLink: $("menu-history-link"),
  menuEngineStatus: $("menu-engine-status-text"),
  menuFfmpegStatus: $("menu-ffmpeg-status"),
  menuExtractorStatus: $("menu-extractor-status"),
  openSettings: $("open-settings"),
  settings: $("settings-dialog"),
  themeSelect: $("theme-select"),
  outputDirectory: $("output-directory-input"),
  saveSettings: $("save-settings-button"),
  settingsMessage: $("settings-save-message"),
  allowedDomains: $("allowed-domains-input"),
  allowedDomainsField: $("allowed-domains-field"),
  saveDomains: $("save-domains-button"),
  domainsMessage: $("domains-save-message"),
  universalMode: $("universal-mode-toggle"),
  cookiesStatusBadge: $("cookies-status-badge"),
  cookiesFileInput: $("cookies-file-input"),
  pasteCookiesBtn: $("paste-cookies-button"),
  clearCookiesBtn: $("clear-cookies-button"),
  cookiesPasteBox: $("cookies-paste-box"),
  cookiesTextarea: $("cookies-textarea"),
  saveCookiesTextBtn: $("save-cookies-text-button"),
  cancelCookiesTextBtn: $("cancel-cookies-text-button"),
  cookiesSaveMessage: $("cookies-save-message"),
  dependencyList: $("dependency-list"),
  refreshDependencies: $("refresh-dependencies"),

  // Download Window elements
  cardEmptyState: $("card-empty-state"),
  closeMediaCard: $("close-media-card"),
  closeJobPanel: $("close-job-panel"),
  card: $("media-card"),
  thumbImg: $("media-thumb-img"),
  thumbFallback: $("media-thumb-fallback"),
  title: $("media-title"),
  mediaSpecs: $("media-specs"),
  source: $("media-source"),
  duration: $("media-duration"),
  size: $("media-size"),
  quality: $("quality-select"),
  format: $("format-select"),
  output: $("output-select"),
  download: $("download-button"),
  downloadHint: $("download-hint"),

  // Job panel elements
  panel: $("job-panel"),
  jobHeadTitle: $("job-head-title"),
  jobCompleteCheck: $("job-complete-check"),
  jobSaveConfirmation: $("job-save-confirmation"),
  jobSaveText: $("job-save-text"),
  jobProgressSection: $("job-progress-section"),
  jobThumbImg: $("job-thumb-img"),
  jobThumbFallback: $("job-thumb-fallback"),
  jobTitle: $("job-title"),
  jobSpecs: $("job-specs"),
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

  // Queue, batch and extractor update
  queueSection: $("queue-section"),
  queueList: $("queue-list"),
  queueClear: $("queue-clear-finished"),
  batchMode: $("batch-mode"),
  extractorText: $("extractor-update-text"),
  extractorCheck: $("extractor-check-button"),
  extractorUpdate: $("extractor-update-button"),
  extractorMessage: $("extractor-update-message"),

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

export function showEmptyWindow() {
  if (els.cardEmptyState) els.cardEmptyState.hidden = false;
  if (els.card) els.card.hidden = true;
  if (els.panel) els.panel.hidden = true;
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
  if (els.themeModeText) {
    els.themeModeText.textContent = activeDark ? "Dark Mode" : "Light Mode";
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
  if (els.dependencyList) {
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

  if (els.menuEngineStatus) {
    const allOk = deps.backend?.ok && deps.ffmpeg?.ok && deps.extractor?.ok;
    els.menuEngineStatus.textContent = allOk ? "Ready to Download" : "Attention Needed";
  }
  if (els.menuFfmpegStatus && deps.ffmpeg) {
    const ver = deps.ffmpeg.version ? deps.ffmpeg.version.split("-")[0].trim() : "";
    els.menuFfmpegStatus.textContent = deps.ffmpeg.ok ? `FFmpeg: Active ${ver}` : "FFmpeg: Not detected";
  }
  if (els.menuExtractorStatus && deps.extractor) {
    const ver = deps.extractor.version ? `(${deps.extractor.version.trim()})` : "Universal";
    els.menuExtractorStatus.textContent = deps.extractor.ok ? `Extractor: Active ${ver}` : "Extractor: Not ready";
  }
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

    // Media Thumbnail box
    const thumbBox = document.createElement("div");
    thumbBox.className = "history-thumb-box";
    const thumbSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    thumbSvg.setAttribute("viewBox", "0 0 24 24");
    thumbSvg.setAttribute("width", "20");
    thumbSvg.setAttribute("height", "20");
    thumbSvg.setAttribute("fill", "none");
    thumbSvg.setAttribute("stroke", "currentColor");
    thumbSvg.setAttribute("stroke-width", "2");
    thumbSvg.setAttribute("stroke-linecap", "round");
    thumbSvg.setAttribute("stroke-linejoin", "round");
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", "2"); rect.setAttribute("y", "2"); rect.setAttribute("width", "20"); rect.setAttribute("height", "20"); rect.setAttribute("rx", "4");
    const poly = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    poly.setAttribute("points", "10 8 16 12 10 16 10 8");
    thumbSvg.append(rect, poly);
    thumbBox.appendChild(thumbSvg);

    const info = document.createElement("div");
    info.className = "history-info";

    const title = document.createElement("h3");
    title.className = "history-title";
    title.textContent = item.title || item.filename || "Untitled";
    title.title = item.title || item.filename || "";

    const meta = document.createElement("p");
    meta.className = "history-meta";

    const parts = [];
    if (item.format_label) parts.push(item.format_label.toUpperCase());
    if (item.file_size > 0) parts.push(formatSize(item.file_size));
    const relTime = formatRelativeTime(item.completed_at);
    if (relTime) parts.push(relTime);
    meta.textContent = parts.join(" · ");

    if (!item.file_exists) {
      const missing = document.createElement("span");
      missing.className = "missing-badge";
      missing.textContent = "(File missing or moved)";
      meta.appendChild(missing);
    }

    info.append(title, meta);
    main.append(thumbBox, info);

    const actions = document.createElement("div");
    actions.className = "history-actions";

    // Completed badge
    const badge = document.createElement("span");
    badge.className = "history-status-badge completed";
    const checkSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    checkSvg.setAttribute("viewBox", "0 0 24 24");
    checkSvg.setAttribute("width", "14");
    checkSvg.setAttribute("height", "14");
    checkSvg.setAttribute("fill", "currentColor");
    const checkPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    checkPath.setAttribute("fill-rule", "evenodd");
    checkPath.setAttribute("clip-rule", "evenodd");
    checkPath.setAttribute("d", "M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2zm4.707 7.707a1 1 0 0 0-1.414-1.414L10 13.586l-2.293-2.293a1 1 0 0 0-1.414 1.414l3 3a1 1 0 0 0 1.414 0l6-6z");
    checkSvg.appendChild(checkPath);
    const badgeText = document.createTextNode(" Completed");
    badge.append(checkSvg, badgeText);

    const openFileBtn = document.createElement("button");
    openFileBtn.type = "button";
    openFileBtn.className = "button small primary";
    openFileBtn.textContent = "Open";
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

    actions.append(badge, openFileBtn, openFolderBtn, deleteBtn);
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

export function setCookiesMessage(state, text) {
  if (!els.cookiesSaveMessage) return;
  els.cookiesSaveMessage.dataset.state = state;
  els.cookiesSaveMessage.textContent = text;
}

export function renderCookiesStatus(status) {
  if (!els.cookiesStatusBadge) return;
  if (status.has_cookies) {
    els.cookiesStatusBadge.textContent = "Cookies active";
    els.cookiesStatusBadge.dataset.state = "ok";
    if (els.clearCookiesBtn) els.clearCookiesBtn.hidden = false;
    let hint = `Active (${status.line_count} entries)`;
    if (status.domains_authenticated && status.domains_authenticated.length > 0) {
      hint += ` · ${status.domains_authenticated.slice(0, 4).join(", ")}`;
    }
    setCookiesMessage("ok", hint);
  } else {
    els.cookiesStatusBadge.textContent = "No cookies";
    els.cookiesStatusBadge.dataset.state = "";
    if (els.clearCookiesBtn) els.clearCookiesBtn.hidden = true;
    setCookiesMessage("", "Public media works out of the box. Import cookies for private / login-only content.");
  }
}
