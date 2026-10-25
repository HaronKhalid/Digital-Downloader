// Thin client for the local backend. The session token is injected into the page by the
// server and sent with every request; other websites cannot read it.

let token = document.querySelector('meta[name="session-token"]')?.content ?? "";
if (token === "__SESSION_TOKEN__") token = "";

export async function ensureSessionToken() {
  if (token && token !== "__SESSION_TOKEN__") return token;
  const base = getBackendBaseUrl();
  try {
    const res = await fetch(`${base}/api/health`, { method: "GET", cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      if (data && data.token) {
        token = data.token;
        return token;
      }
    }
  } catch (_) {}
  return token;
}

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export function getBackendBaseUrl() {
  if (window.AndroidBridge && typeof window.AndroidBridge.getBackendUrl === "function") {
    try {
      const bridgeUrl = window.AndroidBridge.getBackendUrl();
      if (bridgeUrl && bridgeUrl !== "http://10.0.2.2:8000") return bridgeUrl.replace(/\/+$/, "");
    } catch (_) {}
  }
  const stored = localStorage.getItem("digital_downloader_backend_url") || localStorage.getItem("linkfetch_backend_url");
  if (stored) return stored.replace(/\/+$/, "");
  return "";
}

export function setBackendBaseUrl(url) {
  const clean = (url || "").trim().replace(/\/+$/, "");
  if (clean) {
    localStorage.setItem("digital_downloader_backend_url", clean);
    localStorage.setItem("linkfetch_backend_url", clean);
  } else {
    localStorage.removeItem("digital_downloader_backend_url");
    localStorage.removeItem("linkfetch_backend_url");
  }
  if (window.AndroidBridge && typeof window.AndroidBridge.setBackendUrl === "function") {
    try {
      window.AndroidBridge.setBackendUrl(clean);
    } catch (_) {}
  }
}

async function request(method, path, body) {
  const base = getBackendBaseUrl();
  const url = base ? `${base}${path}` : path;
  if (!token || token === "__SESSION_TOKEN__") {
    await ensureSessionToken();
  }
  let response;
  try {
    response = await fetch(url, {
      method,
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Session-Token": token },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      "BACKEND_UNREACHABLE",
      "The backend isn't responding. Check that the server is running and the URL is reachable.",
      0,
    );
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    /* non-JSON body */
  }

  if (!response.ok) {
    const error = data?.error;
    throw new ApiError(
      error?.code ?? "UNKNOWN_ERROR",
      error?.message ?? "Something went wrong. Try again.",
      response.status,
    );
  }
  return data;
}

export const api = {
  health: () => request("GET", "/api/health"),
  dependencies: () => request("GET", "/api/system/dependencies"),
  analyze: (url) => request("POST", "/api/media/analyze", { url }),
  createJob: (payload) => request("POST", "/api/jobs", payload),
  getJob: (id) => request("GET", `/api/jobs/${encodeURIComponent(id)}`),
  listJobs: () => request("GET", "/api/jobs"),
  cancelJob: (id) => request("POST", `/api/jobs/${encodeURIComponent(id)}/cancel`),
  openJob: (id, action = "file") => request("POST", `/api/jobs/${encodeURIComponent(id)}/open`, { action: action || "file" }),
  openJobFolder: (id) => request("POST", `/api/jobs/${encodeURIComponent(id)}/open`, { action: "folder" }),
  history: (limit = 50) => request("GET", `/api/history?limit=${encodeURIComponent(limit)}`),
  getHistory: (id) => request("GET", `/api/history/${encodeURIComponent(id)}`),
  deleteHistory: (id) => request("DELETE", `/api/history/${encodeURIComponent(id)}`),
  openHistory: (id, action) => request("POST", `/api/history/${encodeURIComponent(id)}/open`, { action }),
  settings: () => request("GET", "/api/settings"),
  updateSettings: (payload) =>
    request("PUT", "/api/settings", typeof payload === "string" ? { output_directory: payload } : payload),
  getCookies: () => request("GET", "/api/settings/cookies"),
  updateCookies: (content) => request("POST", "/api/settings/cookies", { cookies_content: content }),
  deleteCookies: () => request("DELETE", "/api/settings/cookies"),
};
