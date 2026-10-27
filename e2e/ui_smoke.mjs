import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const ROOT = new URL("../frontend", import.meta.url).pathname;
let html = readFileSync(`${ROOT}/index.html`, "utf-8").replace(/<script[\s\S]*?<\/script>/g, "");
html = html.replace("__SESSION_TOKEN__", "test-token");
const dom = new JSDOM(html, { url: "http://127.0.0.1:8000/", pretendToBeVisual: true });
const { window } = dom;
for (const key of ["window", "document", "localStorage", "navigator", "CustomEvent", "Event", "HTMLElement"]) {
  Object.defineProperty(globalThis, key, { value: key === "window" ? window : window[key], configurable: true, writable: true });
}
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.HTMLElement.prototype.scrollIntoView = () => {};

const calls = [];
let jobs = [];
const json = (body, status = 200) => ({
  ok: status < 400, status,
  headers: { get: () => "application/json" },
  json: async () => body, text: async () => JSON.stringify(body),
});
globalThis.fetch = async (url, init = {}) => {
  const path = String(url).replace("http://127.0.0.1:8000", "");
  const body = init.body ? JSON.parse(init.body) : null;
  calls.push({ method: init.method || "GET", path, body });
  if (path === "/api/health") return json({ status: "ok" });
  if (path === "/api/system/dependencies")
    return json({ backend: { ok: true, version: "2" }, python: { ok: true, version: "3" }, ffmpeg: { ok: true, version: "6.1-x" }, extractor: { ok: true, version: "2026.10.21" } });
  if (path.startsWith("/api/history")) return json({ items: [] });
  if (path === "/api/settings") return json({ output_directory: "X", allowed_source_domains: ["*"], universal_mode: true });
  if (path === "/api/settings/cookies") return json({ has_cookies: false, size_bytes: 0 });
  if (path === "/api/jobs/batch")
    return json({
      items: body.urls.map((u, i) => ({ url: u, ok: i !== 1, job_id: i !== 1 ? `id-${i}` : null, title: `T${i}`, error: i === 1 ? "Not supported" : null })),
      queued: body.urls.length - 1, failed: 1,
    });
  if (path === "/api/jobs" && (init.method || "GET") === "GET") return json({ jobs });
  if (path.endsWith("/retry")) return json({ job_id: "new-1", status: "queued" }, 202);
  if (path === "/api/system/extractor/update" && (init.method || "GET") === "GET")
    return json({ current: "2026.10.21", latest: "2026.11.01", update_available: true, supported: true });
  if (path === "/api/system/extractor/update") return json({ previous: "2026.10.21", installed: "2026.11.01" });
  return json({ error: { code: "NOT_FOUND", message: "nope" } }, 404);
};

const snap = (o) => ({ job_id: "a", status: "downloading", title: "Clip", progress: 42.4, stage: "", downloaded_bytes: 1, total_bytes: 2, speed_bps: 3e6, eta_seconds: 12, filename: null, file_size: null, error: null, ...o });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (id) => document.getElementById(id);

// ---- queue rendering -------------------------------------------------------
const queue = await import(`${ROOT}/js/queue.js`);
const hostile = '<img src=x onerror="window.__xss=1"> Evil';
jobs = [
  snap({ job_id: "a", title: hostile }),
  snap({ job_id: "b", status: "queued", progress: 0, speed_bps: null, eta_seconds: null }),
  snap({ job_id: "c", status: "failed", error: { code: "X", message: "Gone" } }),
  snap({ job_id: "d", status: "completed", file_size: 5_000_000, progress: 100 }),
];
assert.equal(queue.renderQueue(jobs), true, "reports active jobs");
assert.equal($("queue-section").hidden, false);
const items = [...$("queue-list").children];
assert.equal(items.length, 4);
assert.equal(items[0].querySelector(".queue-title").textContent, hostile, "title is plain text");
assert.equal(window.__xss, undefined, "no markup injection");
assert.match(items[0].querySelector(".queue-status").textContent, /42%.*left/);
assert.equal(items[2].dataset.state, "failed");
const vis = (li, label) => [...li.querySelectorAll("button")].filter((b) => !b.hidden).map((b) => b.textContent).includes(label);
assert.ok(vis(items[0], "Cancel") && !vis(items[0], "Retry"));
assert.ok(vis(items[2], "Retry") && vis(items[2], "Dismiss") && !vis(items[2], "Cancel"));
assert.ok(vis(items[3], "Open"));

// rows are reused (not recreated) and removed when gone
const firstNode = items[0];
queue.renderQueue([snap({ job_id: "a", progress: 80 })]);
assert.equal($("queue-list").children.length, 1);
assert.equal($("queue-list").firstChild, firstNode, "row node reused so focus is kept");
assert.equal(queue.renderQueue([]), false);
assert.equal($("queue-section").hidden, true);

// retry button calls the API and dismisses the old row
queue.renderQueue([snap({ job_id: "c", status: "failed", error: { code: "X", message: "Gone" } })]);
[...$("queue-list").querySelectorAll("button")].find((b) => b.textContent === "Retry").click();
await wait(30);
assert.ok(calls.some((c) => c.path === "/api/jobs/c/retry" && c.method === "POST"), "retry endpoint called");

// ---- app: batch paste ------------------------------------------------------
jobs = [];
await import(`${ROOT}/js/app.js`);
await wait(150);
const input = $("url-input");
input.value = "https://a.example/1 https://b.example/2 https://a.example/1 https://c.example/3";
input.dispatchEvent(new window.Event("input"));
assert.equal($("analyze-button").textContent, "Queue 3 links", "duplicates not counted");
assert.equal($("batch-mode").hidden, false);

// pasting text that contains line breaks is turned into space-separated links
const pasteEvent = new window.Event("paste", { bubbles: true, cancelable: true });
pasteEvent.clipboardData = { getData: () => "https://x.example/1\nhttps://y.example/2\r\nhttps://z.example/3" };
input.value = "";
input.dispatchEvent(pasteEvent);
assert.equal(pasteEvent.defaultPrevented, true);
assert.equal(input.value, "https://x.example/1 https://y.example/2 https://z.example/3");

input.value = "https://a.example/1 https://b.example/2 https://c.example/3";
$("batch-mode").value = "audio";
input.dispatchEvent(new window.Event("input"));
$("url-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await wait(100);
const batchCall = calls.find((c) => c.path === "/api/jobs/batch");
assert.deepEqual(batchCall.body, { urls: ["https://a.example/1", "https://b.example/2", "https://c.example/3"], mode: "audio" });
assert.match($("notice-text").textContent, /Queued 2, skipped 1.*Not supported/);
assert.equal(input.value, "https://b.example/2", "only the failed link stays for fixing");

// invalid link in a batch is rejected locally, nothing sent
const before = calls.filter((c) => c.path === "/api/jobs/batch").length;
input.value = "https://a.example/1 not-a-link";
input.dispatchEvent(new window.Event("input"));
$("url-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await wait(50);
assert.equal(calls.filter((c) => c.path === "/api/jobs/batch").length, before);
assert.match($("notice-text").textContent, /not a valid link/);

// ---- extractor update ------------------------------------------------------
$("extractor-check-button").click();
await wait(60);
assert.equal($("extractor-update-button").hidden, false);
assert.match($("extractor-update-text").textContent, /2026\.10\.21.*2026\.11\.01/);
$("extractor-update-button").click();
await wait(60);
assert.match($("extractor-update-message").textContent, /Updated/);
assert.equal($("extractor-update-button").hidden, true);

console.log("UI smoke test: all assertions passed");
process.exit(0);
