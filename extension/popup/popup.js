const $ = (id) => document.getElementById(id);

function say(el, text, kind) { el.textContent = text; el.className = kind || ""; }

async function activeTab() {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function show() {
  const pairing = await getPairing();
  $("paired").hidden = !pairing;
  $("pairing").hidden = !!pairing;
  if (!pairing) return;
  const tab = await activeTab();
  $("page-title").textContent = (tab && tab.title) || "";
  const r = await ping();
  if (!r.ok) say($("status"), r.message, "err");
  const [{ result } = {}] = await api.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => [...document.querySelectorAll("a[href]")].map((a) => a.href),
  }).catch(() => [{}]);
  const links = [...new Set((result || []).filter((u) => /^https?:\/\//.test(u)))];
  if (links.length > 1) {
    $("send-links").hidden = false;
    $("send-links").textContent = `Send ${Math.min(links.length, 25)} links found on this page`;
    $("send-links").onclick = () => run(links.slice(0, 25), "best");
  }
}

async function run(urls, mode) {
  say($("status"), "Sending…");
  const r = await sendLinks(urls, mode);
  say($("status"), r.message, r.ok ? "ok" : "err");
}

$("send-video").onclick = async () => run([(await activeTab()).url], "best");
$("send-audio").onclick = async () => run([(await activeTab()).url], "audio");

$("connect").onclick = async () => {
  const parsed = parsePairing($("code").value);
  if (!parsed) return say($("pair-status"), "That does not look like a pairing code. Copy it again from the app.", "err");
  await api.storage.local.set(parsed);
  const r = await ping();
  if (!r.ok) {
    await api.storage.local.remove(["port", "key"]);
    return say($("pair-status"), r.message, "err");
  }
  show();
};

$("unpair").onclick = async () => { await api.storage.local.remove(["port", "key"]); show(); };

show();
