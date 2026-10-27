// Thin client for the local backend with seamless Standalone Mobile Extractor support.

let token = document.querySelector('meta[name="session-token"]')?.content ?? "";
if (token === "__SESSION_TOKEN__") token = "";

export function isAndroidApp() {
  return Boolean(
    typeof window !== "undefined" &&
    window.AndroidBridge &&
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
  if (isAndroidApp() && typeof window.AndroidBridge.getBackendUrl === "function") {
    try {
      const bridgeUrl = window.AndroidBridge.getBackendUrl();
      if (bridgeUrl && bridgeUrl !== "http://10.0.2.2:8000") return bridgeUrl.replace(/\/+$/, "");
    } catch (_) {}
  }
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
  if (isAndroidApp() && typeof window.AndroidBridge.setBackendUrl === "function") {
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

// ---------------------------------------------------------------------------
// Standalone Mobile Extractor Engine (Direct Mobile Mode without PC Server)
// ---------------------------------------------------------------------------

const directFormatsCache = new Map();

async function nativeHttpGet(url) {
  if (isAndroidApp() && typeof window.AndroidBridge.httpGet === "function") {
    try {
      const text = window.AndroidBridge.httpGet(url);
      if (typeof text === "string" && (text.trim().startsWith("{") || text.trim().startsWith("["))) {
        return JSON.parse(text);
      }
      return text;
    } catch (_) {}
  }
  const res = await fetch(url, { headers: { Accept: "application/json, text/plain, */*" } });
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return await res.json();
  }
  return await res.text();
}

async function nativeHttpPost(url, body, contentType = "application/json") {
  const bodyStr = typeof body === "string" ? body : JSON.stringify(body);
  if (isAndroidApp() && typeof window.AndroidBridge.httpPost === "function") {
    try {
      const text = window.AndroidBridge.httpPost(url, bodyStr, contentType);
      if (typeof text === "string" && (text.trim().startsWith("{") || text.trim().startsWith("["))) {
        return JSON.parse(text);
      }
      return text;
    } catch (_) {}
  }
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": contentType, Accept: "application/json, text/plain, */*" },
    body: bodyStr,
  });
  const cType = res.headers.get("content-type") || "";
  if (cType.includes("application/json")) {
    return await res.json();
  }
  return await res.text();
}

async function standaloneAnalyze(url) {
  const cleanUrl = url.trim();
  const lower = cleanUrl.toLowerCase();

  // 1. TikTok (via TikWM public direct API)
  if (lower.includes("tiktok.com/")) {
    try {
      const apiUrl = `https://www.tikwm.com/api/?url=${encodeURIComponent(cleanUrl)}`;
      const json = await nativeHttpGet(apiUrl);
      if (json && json.code === 0 && json.data) {
        const d = json.data;
        const title = (d.title || "TikTok Video").trim().slice(0, 150);
        const formats = [];
        if (d.play) {
          formats.push({
            id: "fmt_tiktok_hd",
            type: "video",
            container: "mp4",
            resolution: "HD",
            has_audio: true,
            filesize: d.size || null,
            label: "HD Video (No Watermark) · MP4",
            download_url: d.play,
          });
          directFormatsCache.set("fmt_tiktok_hd", { url: d.play, filename: `${title}.mp4`, mime: "video/mp4" });
        }
        if (d.music) {
          formats.push({
            id: "fmt_tiktok_music",
            type: "audio",
            container: "mp3",
            resolution: null,
            has_audio: true,
            filesize: null,
            label: `Original Audio (${d.music_info?.author || "MP3"})`,
            download_url: d.music,
          });
          directFormatsCache.set("fmt_tiktok_music", { url: d.music, filename: `${title}.mp3`, mime: "audio/mp3" });
        }
        if (formats.length > 0) {
          return {
            source_id: "tiktok_direct",
            source_label: "TikTok",
            url: cleanUrl,
            title,
            thumbnail_url: d.cover || d.origin_cover || null,
            duration: d.duration || null,
            formats,
          };
        }
      }
    } catch (e) {
      console.warn("Direct TikTok extraction failed:", e);
    }
  }

  // 2. Direct Video / Audio Link
  const directMatch = cleanUrl.match(/\.([a-z0-9]{3,4})(?:\?|#|$)/i);
  if (directMatch) {
    const ext = directMatch[1].toLowerCase();
    if (["mp4", "webm", "mkv", "mov", "mp3", "m4a", "wav", "aac"].includes(ext)) {
      const isVideo = ["mp4", "webm", "mkv", "mov"].includes(ext);
      const filename = cleanUrl.split("/").pop().split("?")[0] || `media.${ext}`;
      const title = filename.replace(/\.[^.]+$/, "");
      const fmtId = `direct_${ext}`;
      directFormatsCache.set(fmtId, { url: cleanUrl, filename, mime: isVideo ? `video/${ext}` : `audio/${ext}` });
      return {
        source_id: "direct_link",
        source_label: "Direct Media Link",
        url: cleanUrl,
        title,
        thumbnail_url: null,
        duration: null,
        formats: [
          {
            id: fmtId,
            type: isVideo ? "video" : "audio",
            container: ext,
            resolution: isVideo ? "Original" : null,
            has_audio: true,
            filesize: null,
            label: `${isVideo ? "Direct Video" : "Direct Audio"} · ${ext.toUpperCase()}`,
            download_url: cleanUrl,
          },
        ],
      };
    }
  }

  // 3. YouTube (via Invidious instances)
  const ytMatch = cleanUrl.match(/(?:youtube\.com\/(?:watch\?.*v=|shorts\/|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
  if (ytMatch) {
    const videoId = ytMatch[1];
    const invidiousInstances = [
      "https://inv.nadeko.net",
      "https://invidious.nerdvpn.de",
      "https://yt.artemislena.eu",
      "https://invidious.private.coffee",
      "https://vid.priv.au",
    ];

    for (const inst of invidiousInstances) {
      try {
        const invData = await nativeHttpGet(`${inst}/api/v1/videos/${videoId}`);
        if (invData && invData.title) {
          const title = invData.title.trim().slice(0, 150);
          const formats = [];
          const streams = invData.formatStreams || [];
          for (let i = 0; i < streams.length; i++) {
            const s = streams[i];
            const fid = `yt_${videoId}_${s.quality || i}`;
            formats.push({
              id: fid,
              type: "video",
              container: s.container || "mp4",
              resolution: s.quality || s.resolution || "720p",
              has_audio: true,
              filesize: s.size ? parseInt(s.size, 10) : null,
              label: `${s.quality || s.resolution || "Video"} · ${(s.container || "MP4").toUpperCase()}`,
              download_url: s.url,
            });
            directFormatsCache.set(fid, { url: s.url, filename: `${title}.${s.container || "mp4"}`, mime: "video/mp4" });
          }

          const adaptive = invData.adaptiveFormats || [];
          const audioStream = adaptive.find((a) => (a.type || "").startsWith("audio/"));
          if (audioStream) {
            const fid = `yt_${videoId}_audio`;
            formats.push({
              id: fid,
              type: "audio",
              container: audioStream.container || "m4a",
              resolution: null,
              has_audio: true,
              filesize: audioStream.clen ? parseInt(audioStream.clen, 10) : null,
              label: `Audio Only · ${(audioStream.container || "M4A").toUpperCase()}`,
              download_url: audioStream.url,
            });
            directFormatsCache.set(fid, {
              url: audioStream.url,
              filename: `${title}.${audioStream.container || "m4a"}`,
              mime: "audio/mp4",
            });
          }

          if (formats.length > 0) {
            return {
              source_id: "youtube_invidious",
              source_label: "YouTube",
              url: cleanUrl,
              title,
              thumbnail_url: invData.videoThumbnails?.[0]?.url || `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`,
              duration: invData.lengthSeconds || null,
              formats,
            };
          }
        }
      } catch (_) {}
    }
  }

  // 4. Cobalt v10 / v11 instances for multi-platform media (Instagram, X/Twitter, YouTube, Reddit, Facebook)
  const cobaltInstances = [
    "https://rue-cobalt.xenon.zone",
    "https://cobaltapi.cjs.nz",
    "https://api-cobalt.eversiege.network",
    "https://cobaltapi.squair.xyz",
    "https://cobaltapi.kittycat.boo",
    "https://cobalt-api.lamps-dev.dev",
    "https://apicobalt.girlskissing.top",
  ];

  for (const cInst of cobaltInstances) {
    try {
      const payload = {
        url: cleanUrl,
        videoQuality: "1080",
        downloadMode: "auto",
      };
      const cobaltRes = await nativeHttpPost(`${cInst}/`, payload, "application/json");
      if (cobaltRes && (cobaltRes.url || cobaltRes.status === "tunnel" || cobaltRes.status === "redirect" || cobaltRes.status === "stream" || cobaltRes.status === "picker")) {
        const streamUrl = cobaltRes.url || (cobaltRes.picker && cobaltRes.picker[0]?.url);
        if (streamUrl) {
          const fid = `cobalt_${Date.now()}`;
          const title = cobaltRes.filename ? cobaltRes.filename.replace(/\.[^.]+$/, "") : "Downloaded Media";
          const ext = cobaltRes.filename?.split(".").pop() || "mp4";
          directFormatsCache.set(fid, { url: streamUrl, filename: cobaltRes.filename || `${title}.${ext}`, mime: `video/${ext}` });
          return {
            source_id: "cobalt",
            source_label: lower.includes("instagram.com") ? "Instagram" : lower.includes("twitter.com") || lower.includes("x.com") ? "X (Twitter)" : "Web Media",
            url: cleanUrl,
            title,
            thumbnail_url: (cobaltRes.picker && cobaltRes.picker[0]?.thumb) || null,
            duration: null,
            formats: [
              {
                id: fid,
                type: "video",
                container: ext,
                resolution: "Original",
                has_audio: true,
                filesize: null,
                label: `HD Media Stream · ${ext.toUpperCase()}`,
                download_url: streamUrl,
              },
            ],
          };
        }
      }
    } catch (_) {}
  }

  // 5. Instagram direct media metadata extraction fallback
  if (lower.includes("instagram.com/")) {
    try {
      // Try resolving Instagram public embed caption HTML
      const shortcodeMatch = cleanUrl.match(/\/(?:reel|reels|p|tv)\/([a-zA-Z0-9_-]+)/);
      if (shortcodeMatch) {
        const shortcode = shortcodeMatch[1];
        const embedUrl = `https://www.instagram.com/p/${shortcode}/embed/caption/`;
        const embedHtml = await nativeHttpGet(embedUrl);
        if (typeof embedHtml === "string") {
          const videoMatch = embedHtml.match(/"video_url"\s*:\s*"([^"]+)"/) || embedHtml.match(/<video[^>]+src="([^"]+)"/);
          if (videoMatch) {
            let directVideoUrl = videoMatch[1].replace(/\\u0026/g, "&").replace(/&amp;/g, "&");
            const fid = `ig_${shortcode}`;
            const title = `Instagram_Reel_${shortcode}`;
            directFormatsCache.set(fid, { url: directVideoUrl, filename: `${title}.mp4`, mime: "video/mp4" });
            return {
              source_id: "instagram_direct",
              source_label: "Instagram Reel",
              url: cleanUrl,
              title: `Instagram Reel (${shortcode})`,
              thumbnail_url: null,
              duration: null,
              formats: [
                {
                  id: fid,
                  type: "video",
                  container: "mp4",
                  resolution: "HD",
                  has_audio: true,
                  filesize: null,
                  label: "Original Video · MP4",
                  download_url: directVideoUrl,
                },
              ],
            };
          }
        }
      }
    } catch (_) {}
  }

  throw new ApiError(
    "EXTRACTION_FAILED",
    "Could not extract downloadable media from this link directly. Check the URL and try again.",
    400,
  );
}

function standaloneCreateJob(payload) {
  const cached = directFormatsCache.get(payload.format_id);
  const downloadUrl = cached?.url;
  const filename = cached?.filename || "media_download.mp4";
  const mime = cached?.mime || "video/mp4";

  if (!downloadUrl) {
    throw new ApiError("FORMAT_EXPIRED", "Format expired. Please analyze the link again.", 400);
  }

  if (isAndroidApp() && typeof window.AndroidBridge.downloadUrlViaSystem === "function") {
    window.AndroidBridge.downloadUrlViaSystem(downloadUrl, filename, mime);
  }

  const jobId = `mob_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`;
  const job = {
    id: jobId,
    url: payload.url,
    state: "completed",
    percent: 100,
    filename: filename,
    target_path: `/storage/emulated/0/Download/${filename}`,
    completed_at: new Date().toISOString(),
  };

  try {
    const raw = localStorage.getItem("digital_downloader_mobile_history") || "[]";
    const history = JSON.parse(raw);
    history.unshift({
      id: jobId,
      url: payload.url,
      title: filename.replace(/\.[^.]+$/, ""),
      target_path: job.target_path,
      filename: filename,
      state: "completed",
      completed_at: job.completed_at,
    });
    localStorage.setItem("digital_downloader_mobile_history", JSON.stringify(history.slice(0, 100)));
  } catch (_) {}

  return job;
}

function standaloneGetHistory() {
  try {
    const raw = localStorage.getItem("digital_downloader_mobile_history") || "[]";
    return JSON.parse(raw);
  } catch (_) {
    return [];
  }
}

export const api = {
  health: async () => {
    if (isAndroidApp() && !getBackendBaseUrl()) {
      return { status: "ok", mode: "standalone_mobile", token: "mobile" };
    }
    try {
      return await request("GET", "/api/health");
    } catch (err) {
      if (isAndroidApp()) {
        return { status: "ok", mode: "standalone_mobile", token: "mobile" };
      }
      throw err;
    }
  },

  dependencies: async () => {
    if (isAndroidApp() && !getBackendBaseUrl()) {
      return {
        backend: { ok: true, version: "2.0.0 (Native Mobile)" },
        python: { ok: true, version: "Standalone Engine" },
        ffmpeg: { ok: true, version: "Android Native Media" },
        extractor: { ok: true, version: "Universal Mobile Extractor" },
      };
    }
    try {
      return await request("GET", "/api/system/dependencies");
    } catch (err) {
      if (isAndroidApp()) {
        return {
          backend: { ok: true, version: "2.0.0 (Native Mobile)" },
          python: { ok: true, version: "Standalone Engine" },
          ffmpeg: { ok: true, version: "Android Native Media" },
          extractor: { ok: true, version: "Universal Mobile Extractor" },
        };
      }
      throw err;
    }
  },

  analyze: async (url) => {
    if (isAndroidApp() && !getBackendBaseUrl()) {
      return await standaloneAnalyze(url);
    }
    try {
      return await request("POST", "/api/media/analyze", { url });
    } catch (err) {
      if (isAndroidApp() || err.code === "BACKEND_UNREACHABLE") {
        return await standaloneAnalyze(url);
      }
      throw err;
    }
  },

  createJob: async (payload) => {
    if (directFormatsCache.has(payload.format_id) || (isAndroidApp() && !getBackendBaseUrl())) {
      return standaloneCreateJob(payload);
    }
    try {
      return await request("POST", "/api/jobs", payload);
    } catch (err) {
      if (isAndroidApp() && directFormatsCache.has(payload.format_id)) {
        return standaloneCreateJob(payload);
      }
      throw err;
    }
  },

  getJob: async (id) => {
    if (String(id).startsWith("mob_")) {
      return {
        id,
        state: "completed",
        percent: 100,
        filename: "Download started in notification bar",
        target_path: "/storage/emulated/0/Download",
      };
    }
    return request("GET", `/api/jobs/${encodeURIComponent(id)}`);
  },

  listJobs: () => request("GET", "/api/jobs"),
  cancelJob: (id) => request("POST", `/api/jobs/${encodeURIComponent(id)}/cancel`),

  openJob: (id, action = "file") => {
    if (isAndroidApp()) {
      if (action === "folder") {
        window.AndroidBridge.openDownloadsFolder?.();
      }
      return Promise.resolve({ ok: true });
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

  history: async (limit = 50) => {
    if (isAndroidApp() && !getBackendBaseUrl()) {
      return standaloneGetHistory().slice(0, limit);
    }
    try {
      return await request("GET", `/api/history?limit=${encodeURIComponent(limit)}`);
    } catch (err) {
      if (isAndroidApp()) {
        return standaloneGetHistory().slice(0, limit);
      }
      throw err;
    }
  },

  getHistory: (id) => request("GET", `/api/history/${encodeURIComponent(id)}`),

  deleteHistory: (id) => {
    if (isAndroidApp() && !getBackendBaseUrl()) {
      try {
        const raw = localStorage.getItem("digital_downloader_mobile_history") || "[]";
        const history = JSON.parse(raw).filter((item) => item.id !== id);
        localStorage.setItem("digital_downloader_mobile_history", JSON.stringify(history));
      } catch (_) {}
      return Promise.resolve({ ok: true });
    }
    return request("DELETE", `/api/history/${encodeURIComponent(id)}`);
  },

  openHistory: (id, action) => {
    if (isAndroidApp()) {
      window.AndroidBridge.openDownloadsFolder?.();
      return Promise.resolve({ ok: true });
    }
    return request("POST", `/api/history/${encodeURIComponent(id)}/open`, { action });
  },

  settings: async () => {
    if (isAndroidApp() && !getBackendBaseUrl()) {
      return {
        output_directory: "Downloads",
        allowed_source_domains: ["*"],
        universal_mode: true,
      };
    }
    try {
      return await request("GET", "/api/settings");
    } catch (err) {
      if (isAndroidApp()) {
        return { output_directory: "Downloads", allowed_source_domains: ["*"], universal_mode: true };
      }
      throw err;
    }
  },

  updateSettings: (payload) => {
    if (isAndroidApp() && !getBackendBaseUrl()) {
      return Promise.resolve({
        output_directory: "Downloads",
        allowed_source_domains: ["*"],
        universal_mode: true,
      });
    }
    return request("PUT", "/api/settings", typeof payload === "string" ? { output_directory: payload } : payload);
  },

  getCookies: () => {
    if (isAndroidApp() && !getBackendBaseUrl()) {
      return Promise.resolve({ has_cookies: false, size_bytes: 0 });
    }
    return request("GET", "/api/settings/cookies");
  },

  updateCookies: (content) => request("POST", "/api/settings/cookies", { cookies_content: content }),
  deleteCookies: () => request("DELETE", "/api/settings/cookies"),
};
