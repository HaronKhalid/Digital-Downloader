// Background worker: context menu, keyboard shortcut and badge feedback.
if (typeof importScripts === "function") importScripts("lib.js"); // Firefox loads lib.js via manifest scripts

const MENU_PAGE = "dd-send-page";
const MENU_LINK = "dd-send-link";
const MENU_AUDIO = "dd-send-audio";

api.runtime.onInstalled.addListener(() => {
  api.contextMenus.removeAll(() => {
    api.contextMenus.create({ id: MENU_PAGE, title: "Download this page with Digital Downloader", contexts: ["page", "video"] });
    api.contextMenus.create({ id: MENU_LINK, title: "Download this link with Digital Downloader", contexts: ["link"] });
    api.contextMenus.create({ id: MENU_AUDIO, title: "Download audio only (MP3)", contexts: ["page", "link", "video"] });
  });
});

function flash(tabId, ok, message) {
  api.action.setBadgeBackgroundColor({ color: ok ? "#2e7d32" : "#b3261e" });
  api.action.setBadgeText({ text: ok ? "✓" : "!" });
  setTimeout(() => api.action.setBadgeText({ text: "" }), 2500);
  if (!ok && api.notifications) {
    api.notifications.create({ type: "basic", iconUrl: "icons/icon128.png", title: "Digital Downloader", message });
  }
}

async function handle(url, mode, tabId) {
  const r = await sendLinks([url], mode);
  flash(tabId, r.ok, r.message);
}

api.contextMenus.onClicked.addListener((info, tab) => {
  const mode = info.menuItemId === MENU_AUDIO ? "audio" : "best";
  const url = info.linkUrl || info.srcUrl || info.pageUrl || (tab && tab.url);
  handle(url, mode, tab && tab.id);
});

api.commands.onCommand.addListener(async (command) => {
  if (command !== "send-page") return;
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  if (tab && tab.url) handle(tab.url, "best", tab.id);
});
