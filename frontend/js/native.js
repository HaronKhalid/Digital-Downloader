// Bridge to the on-device download engine (Android app only).
//
// The Android app answers each call asynchronously: we hand it a call id, it does the work on a
// background thread and then calls window.__nativeResolve(id, ok, jsonText).

const pending = new Map();
let counter = 0;

window.__nativeResolve = (id, ok, payload) => {
  const entry = pending.get(id);
  if (!entry) return;
  pending.delete(id);
  let data = null;
  try {
    data = JSON.parse(payload);
  } catch {
    /* fall through with null */
  }
  if (ok) entry.resolve(data);
  else entry.reject({ code: data?.code ?? "UNKNOWN_ERROR", message: data?.message ?? "Something went wrong. Try again." });
};

export function nativeAvailable() {
  return Boolean(
    typeof window !== "undefined" &&
      window.AndroidBridge &&
      typeof window.AndroidBridge.invoke === "function" &&
      typeof window.AndroidBridge.isAndroidApp === "function" &&
      window.AndroidBridge.isAndroidApp(),
  );
}

/** Calls an engine action. Rejects with {code, message}. */
export function nativeCall(method, args = {}) {
  return new Promise((resolve, reject) => {
    const id = `c${++counter}`;
    pending.set(id, { resolve, reject });
    try {
      window.AndroidBridge.invoke(id, method, JSON.stringify(args));
    } catch {
      pending.delete(id);
      reject({ code: "ENGINE_UNAVAILABLE", message: "The download engine isn't available." });
    }
  });
}

/** Instant reads of the download list (no waiting on the engine). */
export function nativeListDownloads() {
  try {
    const list = JSON.parse(window.AndroidBridge.listDownloads() || "[]");
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

export function nativeGetDownload(id) {
  try {
    const text = window.AndroidBridge.getDownload(String(id));
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}
