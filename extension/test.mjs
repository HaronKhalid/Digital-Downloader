// Run with: node extension/test.mjs   (no browser needed; fakes the extension APIs and the app)
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const store = {};
globalThis.chrome = { storage: { local: {
  get: async (keys) => Object.fromEntries(keys.filter((k) => k in store).map((k) => [k, store[k]])),
  set: async (o) => Object.assign(store, o),
  remove: async (keys) => keys.forEach((k) => delete store[k]),
} } };
const sent = [];
let mode = "ok";
globalThis.fetch = async (url, init) => {
  if (mode === "offline") throw new TypeError("fetch failed");
  const res = (status, body) => ({ status, ok: status < 400, json: async () => body });
  if (init.headers["X-Extension-Key"] !== "GOODKEYGOODKEYGOODKEY") return res(403, { error: { message: "no" } });
  if (url.endsWith("/ping")) return res(200, { ok: true });
  const body = JSON.parse(init.body);
  sent.push({ url, body });
  if (mode === "reject") return res(200, { queued: 0, failed: 1, items: [{ ok: false, error: "Unsupported site" }] });
  return res(200, { queued: body.urls.length, failed: 0, items: [] });
};

const lib = createRequire(import.meta.url)("./lib.js");

assert.deepEqual(lib.parsePairing(" dd1.8000.GOODKEYGOODKEYGOODKEY "), { port: 8000, key: "GOODKEYGOODKEYGOODKEY" });
for (const bad of ["", "hello", "dd1.8000.short", "dd2.8000.GOODKEYGOODKEYGOODKEY", "dd1.x.GOODKEYGOODKEYGOODKEY"]) {
  assert.equal(lib.parsePairing(bad), null, `rejects ${bad}`);
}

assert.equal((await lib.sendLinks(["https://a.example/v"])).reason, "unpaired");

store.port = 8000; store.key = "GOODKEYGOODKEYGOODKEY";
const ok = await lib.sendLinks(["https://a.example/v", "https://a.example/v", "javascript:alert(1)", "chrome://settings"], "audio");
assert.equal(ok.ok, true);
assert.deepEqual(sent.at(-1).body, { urls: ["https://a.example/v"], mode: "audio" }, "dedupes and drops non-web links");
assert.equal(sent.at(-1).url, "http://127.0.0.1:8000/api/extension/send");

assert.equal((await lib.sendLinks(["chrome://settings"])).reason, "nolinks");
const many = Array.from({ length: 40 }, (_, i) => `https://a.example/${i}`);
await lib.sendLinks(many);
assert.equal(sent.at(-1).body.urls.length, 25, "never more than the app accepts");

mode = "reject";
assert.match((await lib.sendLinks(["https://x.example"])).message, /Unsupported site/);
mode = "offline";
assert.equal((await lib.ping()).reason, "offline");
mode = "ok";
store.key = "WRONGWRONGWRONGWRONG";
assert.equal((await lib.ping()).reason, "unpaired", "403 means the pairing code is stale");

console.log("Extension tests: all assertions passed");
