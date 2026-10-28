// Shared helpers (loaded by the popup and imported by the background worker).
const api = (typeof browser !== "undefined" ? browser : chrome);

function parsePairing(code) {
  const m = /^dd1\.(\d{2,5})\.([A-Za-z0-9_-]{16,})$/.exec((code || "").trim());
  if (!m) return null;
  return { port: Number(m[1]), key: m[2] };
}

async function getPairing() {
  const s = await api.storage.local.get(["port", "key"]);
  return s.port && s.key ? { port: s.port, key: s.key } : null;
}

async function call(path, options = {}) {
  const pairing = await getPairing();
  if (!pairing) return { ok: false, reason: "unpaired", message: "Not paired yet. Open the app, go to Settings → Browser extension and copy the pairing code." };
  let response;
  try {
    response = await fetch(`http://127.0.0.1:${pairing.port}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", "X-Extension-Key": pairing.key },
    });
  } catch (e) {
    return { ok: false, reason: "offline", message: "Digital Downloader is not running. Open the app and try again." };
  }
  let data = null;
  try { data = await response.json(); } catch (e) { /* ignore */ }
  if (response.status === 403) return { ok: false, reason: "unpaired", message: "The pairing code is no longer valid. Copy a fresh one from the app's Settings." };
  if (!response.ok) return { ok: false, reason: "error", message: (data && (data.message || (data.error && data.error.message))) || `The app answered with an error (${response.status}).` };
  return { ok: true, data };
}

const ping = () => call("/api/extension/ping");

async function sendLinks(urls, mode = "best") {
  const clean = [...new Set(urls.filter((u) => /^https?:\/\//i.test(u)))].slice(0, 25);
  if (!clean.length) return { ok: false, reason: "nolinks", message: "There is no web link to send here." };
  const r = await call("/api/extension/send", { method: "POST", body: JSON.stringify({ urls: clean, mode }) });
  if (!r.ok) return r;
  const { queued, failed, items } = r.data;
  if (queued === 0) {
    const why = items && items[0] && items[0].error ? items[0].error : "This link is not supported.";
    return { ok: false, reason: "rejected", message: why };
  }
  return { ok: true, queued, failed, message: queued === 1 ? "Added to your downloads." : `${queued} links added to your downloads.` };
}

if (typeof module !== "undefined") module.exports = { parsePairing, sendLinks, ping, call };
