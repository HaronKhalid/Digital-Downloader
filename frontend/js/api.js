// Thin client for the app engine: the local backend on desktop, the on-device engine on Android.
import { nativeCall, nativeGetDownload, nativeListDownloads } from "./native.js";

let token = document.querySelector('meta[name="session-token"]')?.content ?? "";
if (token === "__SESSION_TOKEN__") token = "";

export function isAndroidApp() {
  return Boolean(
    typeof window !== "undefined" &&
    window.AndroidBridge &&
    typeof window.AndroidBridge.invoke === "function" &&
    typeof window.AndroidBridge.isAndroidApp === "function" &&
    window.AndroidBridge.isAndroidApp()
  );
}

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
  if (isAndroidApp()) return ""; // the phone app never talks to a server
  const stored = localStorage.getItem("digital_downloader_backend_url");
  if (stored) return stored.replace(/\/+$/, "");
  return "";
}

export function setBackendBaseUrl(url) {
  const clean = (url || "").trim().replace(/\/+$/, "");
  if (clean) {
    localStorage.setItem("digital_downloader_backend_url", clean);
  } else {
    localStorage.removeItem("digital_downloader_backend_url");
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

// ---------------------------------------------------------------------------
// Android: the download engine runs on the phone itself (yt-dlp + FFmpeg).
// ---------------------------------------------------------------------------

const analysisByUrl = new Map();

async function native(method, args) {
  try {
    return await nativeCall(method, args);
  } catch (err) {
    throw new ApiError(err?.code ?? "UNKNOWN_ERROR", err?.message ?? "Something went wrong. Try again.", 400);
  }
}

export const api = {
  health: () => (isAndroidApp() ? native("health") : request("GET", "/api/health")),

  dependencies: () => (isAndroidApp() ? native("dependencies") : request("GET", "/api/system/dependencies")),

  analyze: async (url) => {
    if (!isAndroidApp()) return request("POST", "/api/media/analyze", { url });
    const result = await native("analyze", { url });
    analysisByUrl.set(url, { title: result.title, thumbnail: result.thumbnail });
    return result;
  },

  createJob: (payload) => {
    if (!isAndroidApp()) return request("POST", "/api/jobs", payload);
    const meta = analysisByUrl.get(payload.url) || {};
    return native("createJob", { ...payload, title: meta.title, thumbnail: meta.thumbnail });
  },

  getJob: async (id) => {
    if (!isAndroidApp()) return request("GET", `/api/jobs/${encodeURIComponent(id)}`);
    const job = nativeGetDownload(id);
    if (!job) throw new ApiError("NOT_FOUND", "That download no longer exists.", 404);
    return job;
  },

  listJobs: async () => {
    if (isAndroidApp()) return nativeListDownloads();
    const res = await request("GET", "/api/jobs");
    // The backend returns {jobs: [...]}; normalise so callers always get an array.
    return Array.isArray(res) ? res : res?.jobs || [];
  },

  cancelJob: (id) =>
    isAndroidApp() ? native("cancel", { id }) : request("POST", `/api/jobs/${encodeURIComponent(id)}/cancel`),

  retryJob: (id) =>
    isAndroidApp() ? native("retry", { id }) : request("POST", `/api/jobs/${encodeURIComponent(id)}/retry`),

  /** Queue several links at once. mode: "best" | "audio". */
  batchJobs: (urls, mode = "best") =>
    isAndroidApp() ? native("batch", { urls, mode }) : request("POST", "/api/jobs/batch", { urls, mode }),

  checkExtractorUpdate: () =>
    isAndroidApp() ? native("extractorCheck") : request("GET", "/api/system/extractor/update"),

  updateExtractor: () =>
    isAndroidApp() ? native("extractorUpdate") : request("POST", "/api/system/extractor/update"),

  openJob: (id, action = "file") => {
    if (isAndroidApp()) {
      if (action === "folder") {
        window.AndroidBridge.openDownloadsFolder?.();
        return Promise.resolve({ ok: true });
      }
      return native("openFile", { id });
    }
    return request("POST", `/api/jobs/${encodeURIComponent(id)}/open`, { action: action || "file" });
  },

  openJobFolder: (id) => {
    if (isAndroidApp()) {
      window.AndroidBridge.openDownloadsFolder?.();
      return Promise.resolve({ ok: true });
    }
    return request("POST", `/api/jobs/${encodeURIComponent(id)}/open`, { action: "folder" });
  },

  history: (limit = 50) =>
    isAndroidApp() ? native("history", { limit }) : request("GET", `/api/history?limit=${encodeURIComponent(limit)}`),

  getHistory: (id) => request("GET", `/api/history/${encodeURIComponent(id)}`),

  deleteHistory: (id) =>
    isAndroidApp() ? native("deleteHistory", { id }) : request("DELETE", `/api/history/${encodeURIComponent(id)}`),

  openHistory: (id, action) => {
    if (isAndroidApp()) {
      if (action === "folder") {
        window.AndroidBridge.openDownloadsFolder?.();
        return Promise.resolve({ ok: true });
      }
      return native("openFile", { id });
    }
    return request("POST", `/api/history/${encodeURIComponent(id)}/open`, { action });
  },

  extensionPairing: () => request("GET", "/api/extension/pairing"),
  rotateExtensionPairing: () => request("POST", "/api/extension/pairing/rotate"),
  openExtensionFolder: () => request("POST", "/api/extension/open-folder"),

  settings: () => (isAndroidApp() ? native("settings") : request("GET", "/api/settings")),

  updateSettings: (payload) => {
    if (isAndroidApp()) return native("updateSettings", typeof payload === "string" ? {} : payload);
    return request("PUT", "/api/settings", typeof payload === "string" ? { output_directory: payload } : payload);
  },

  getCookies: () => (isAndroidApp() ? native("getCookies") : request("GET", "/api/settings/cookies")),

  updateCookies: (content) =>
    isAndroidApp()
      ? native("updateCookies", { cookies_content: content })
      : request("POST", "/api/settings/cookies", { cookies_content: content }),

  deleteCookies: () => (isAndroidApp() ? native("deleteCookies") : request("DELETE", "/api/settings/cookies")),
};
