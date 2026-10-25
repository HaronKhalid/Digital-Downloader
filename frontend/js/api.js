// Thin client for the local backend. The session token is injected into the page by the
// server and sent with every request; other websites cannot read it.

const token = document.querySelector('meta[name="session-token"]')?.content ?? "";

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Session-Token": token },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      "BACKEND_UNREACHABLE",
      "The local backend isn't responding. Check that the application is still running.",
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
  openJob: (id, action) => request("POST", `/api/jobs/${encodeURIComponent(id)}/open`, { action }),
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
