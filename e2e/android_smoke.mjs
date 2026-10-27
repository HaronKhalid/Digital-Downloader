// Simulates the Android app: a fake AndroidBridge answers the same way the Kotlin code does.
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const ROOT = new URL("../frontend", import.meta.url).pathname;
let html = readFileSync(`${ROOT}/index.html`, "utf-8").replace(/<script[\s\S]*?<\/script>/g, "");
const dom = new JSDOM(html, { url: "https://appassets.androidplatform.net/assets/index.html", pretendToBeVisual: true });
const { window } = dom;
for (const key of ["window", "document", "localStorage", "navigator", "CustomEvent", "Event", "HTMLElement"]) {
  Object.defineProperty(globalThis, key, { value: key === "window" ? window : window[key], configurable: true, writable: true });
}
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.HTMLElement.prototype.scrollIntoView = () => {};
// jsdom has no <dialog> support
window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
window.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };

const calls = [];
let downloads = [];
const snap = (o) => ({ job_id: "a", status: "downloading", title: "Clip", progress: 30, stage: "Downloading", downloaded_bytes: 1, total_bytes: 2, speed_bps: 1e6, eta_seconds: 5, filename: null, file_size: null, error: null, ...o });

const answer = (method, args) => {
  switch (method) {
    case "health": return { status: "ok", mode: "native" };
    case "dependencies":
      return { backend: { ok: true, version: "2.1.0" }, python: { ok: true, version: "built in" }, ffmpeg: { ok: true, version: "built in" }, extractor: { ok: true, version: "2026.10.21" } };
    case "analyze":
      return { source: "ytdlp", source_label: "Youtube", url: args.url, title: "Native clip", duration: 61, thumbnail: null,
        formats: [{ id: "v1080", type: "video", container: "mp4", resolution: "1080p", has_audio: true, filesize: 5e6, filesize_approximate: true, label: "1080p · MP4" },
                  { id: "audio", type: "audio", container: "m4a", resolution: null, has_audio: true, filesize: 1e6, filesize_approximate: true, label: "Audio only · M4A" }] };
    case "createJob": downloads = [snap({ job_id: "n1", title: args.title })]; return { job_id: "n1", status: "queued" };
    case "batch": return { items: args.urls.map((u) => ({ url: u, ok: true, job_id: "x", title: null, error: null })), queued: args.urls.length, failed: 0 };
    case "history": return { items: [] };
    case "settings": return { output_directory: "Downloads/DigitalDownloader", allowed_source_domains: ["*"], universal_mode: true, share_mode: "background", share_quality: "best" };
    case "updateSettings": return { ...answer("settings"), ...args };
    case "getCookies": return { has_cookies: false, size_bytes: 0 };
    case "cancel": case "retry": case "openFile": return { ok: true, job_id: "r1", status: "queued" };
    default: throw { code: "NOT_FOUND", message: "Unknown action." };
  }
};

window.AndroidBridge = {
  isAndroidApp: () => true,
  invoke(id, method, argsJson) {
    const args = JSON.parse(argsJson);
    calls.push({ method, args });
    setTimeout(() => {
      try {
        window.__nativeResolve(id, true, JSON.stringify(answer(method, args)));
      } catch (e) {
        window.__nativeResolve(id, false, JSON.stringify(e));
      }
    }, 5);
  },
  listDownloads: () => JSON.stringify(downloads),
  getDownload: (id) => { const j = downloads.find((d) => d.job_id === id); return j ? JSON.stringify(j) : ""; },
  getSharedUrl: () => "https://a.example/1 https://b.example/2",
  getClipboardText: () => "",
  openDownloadsFolder: () => calls.push({ method: "folder" }),
  vibrate: () => {},
};

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (id) => document.getElementById(id);

const { api } = await import(`${ROOT}/js/api.js`);

// plain calls round-trip through the bridge
assert.equal((await api.health()).mode, "native");
const info = await api.analyze("https://y.example/v");
assert.equal(info.title, "Native clip");
const created = await api.createJob({ url: "https://y.example/v", format_id: "v1080" });
assert.equal(created.job_id, "n1");
const createCall = calls.find((c) => c.method === "createJob");
assert.equal(createCall.args.title, "Native clip", "title from the analysis is sent along");

// polling reads come straight from the bridge
assert.equal((await api.getJob("n1")).title, "Native clip");
await assert.rejects(() => api.getJob("missing"), (e) => e.status === 404 && e.code === "NOT_FOUND");
assert.equal((await api.listJobs()).length, 1);

// engine errors become ApiError with the engine's message
await assert.rejects(() => api.cancelJob("zzz").then(() => api.updateCookies("x")), (e) => e.code === "NOT_FOUND");

// a hostile title stays plain text in the queue
const queue = await import(`${ROOT}/js/queue.js`);
queue.renderQueue([snap({ job_id: "h", title: '<img src=x onerror="window.__xss=1">' })]);
assert.equal(window.__xss, undefined);

// the page picks up links shared before it loaded, and queues them as a batch
await import(`${ROOT}/js/app.js`);
await wait(200);
assert.ok(calls.some((c) => c.method === "batch" && c.args.urls.length === 2), "shared links were queued natively");

// settings: Android-only block is visible and saves through the bridge
$("open-settings")?.click();
await wait(100);
assert.equal($("android-share-settings").hidden, false);
assert.equal($("output-directory-input").readOnly, true);
$("share-mode-select").value = "open";
$("share-mode-select").dispatchEvent(new window.Event("change"));
await wait(50);
assert.ok(calls.some((c) => c.method === "updateSettings" && c.args.share_mode === "open"));

console.log("Android bridge smoke test: all assertions passed");
process.exit(0);
