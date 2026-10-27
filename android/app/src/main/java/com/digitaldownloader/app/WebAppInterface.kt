package com.digitaldownloader.app

import android.app.DownloadManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.webkit.JavascriptInterface
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * The only door between the web UI and the phone. The page loads from the app's own assets and the
 * bridge never fetches arbitrary addresses: all network work happens inside the download engine.
 */
class WebAppInterface(
    private val activity: MainActivity,
    private val runJs: (String) -> Unit,
) {
    private val ctx: Context = activity.applicationContext
    private val pool = Executors.newFixedThreadPool(4) { r -> Thread(r, "bridge-worker").apply { isDaemon = true } }
    private val store get() = DownloadStore.get(ctx)

    // ---------------------------------------------------------------- simple, instant calls

    @JavascriptInterface
    fun isAndroidApp(): Boolean = true

    @JavascriptInterface
    fun listDownloads(): String {
        val arr = JSONArray()
        store.list(100).forEach { arr.put(it.toJson()) }
        return arr.toString()
    }

    @JavascriptInterface
    fun getDownload(id: String): String = store.get(id)?.toJson()?.toString() ?: ""

    @JavascriptInterface
    fun getSharedUrl(): String? {
        val text = activity.pendingSharedText
        activity.pendingSharedText = null
        return text
    }

    @JavascriptInterface
    fun showToast(message: String) {
        activity.runOnUiThread { Toast.makeText(activity, message, Toast.LENGTH_SHORT).show() }
    }

    @JavascriptInterface
    fun copyToClipboard(text: String) {
        activity.runOnUiThread {
            val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("Digital Downloader", text))
            Toast.makeText(activity, "Copied to clipboard", Toast.LENGTH_SHORT).show()
        }
    }

    @JavascriptInterface
    fun getClipboardText(): String {
        return try {
            val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val clip = clipboard.primaryClip
            if (clip != null && clip.itemCount > 0) clip.getItemAt(0).coerceToText(activity)?.toString()?.trim() ?: "" else ""
        } catch (_: Exception) {
            ""
        }
    }

    @JavascriptInterface
    fun vibrate() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = activity.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
                vm.defaultVibrator.vibrate(VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                val v = activity.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    v.vibrate(VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE))
                } else {
                    @Suppress("DEPRECATION")
                    v.vibrate(50)
                }
            }
        } catch (_: Exception) {
        }
    }

    @JavascriptInterface
    fun openDownloadsFolder() {
        try {
            val intent = Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
        } catch (_: Exception) {
            showToast("Open your Files app and look in Downloads/${MediaSaver.FOLDER}")
        }
    }

    // ---------------------------------------------------------------- asynchronous calls

    /** Runs [method] off the UI thread and answers the page through `window.__nativeResolve`. */
    @JavascriptInterface
    fun invoke(callId: String, method: String, argsJson: String) {
        pool.execute {
            var ok = true
            val payload: String = try {
                val args = if (argsJson.isBlank()) JSONObject() else JSONObject(argsJson)
                (handle(method, args) ?: JSONObject()).toString()
            } catch (e: AppException) {
                ok = false
                errorJson(e.code, e.message)
            } catch (e: Exception) {
                ok = false
                errorJson("UNKNOWN_ERROR", e.message?.take(200) ?: "Something went wrong. Try again.")
            }
            val js = "window.__nativeResolve && window.__nativeResolve(" +
                JSONObject.quote(callId) + "," + ok + "," + JSONObject.quote(payload) + ");"
            runJs(js)
        }
    }

    private fun errorJson(code: String, message: String): String =
        JSONObject().put("code", code).put("message", message).toString()

    private fun handle(method: String, a: JSONObject): Any? = when (method) {
        "health" -> JSONObject().put("status", "ok").put("mode", "native")
        "dependencies" -> dependencies()
        "analyze" -> Engine.analyze(ctx, requireUrl(a.optString("url")))
        "createJob" -> createJob(a)
        "batch" -> batch(a)
        "cancel" -> {
            Downloads.cancel(ctx, a.getString("id"))
            JSONObject().put("ok", true)
        }
        "retry" -> {
            val job = Downloads.retry(ctx, a.getString("id"))
            JSONObject().put("job_id", job.id).put("status", job.status)
        }
        "history" -> history(a.optInt("limit", 50))
        "deleteHistory" -> {
            store.delete(a.getString("id"))
            JSONObject().put("deleted", true)
        }
        "openFile" -> openFile(a.getString("id"))
        "settings" -> settings()
        "updateSettings" -> {
            if (a.has("share_mode")) Prefs.setShareMode(ctx, a.optString("share_mode"))
            if (a.has("share_quality")) Prefs.setShareQuality(ctx, a.optString("share_quality"))
            settings()
        }
        "getCookies" -> cookies()
        "updateCookies" -> saveCookies(a.optString("cookies_content"))
        "deleteCookies" -> {
            Engine.cookieFile(ctx).delete()
            cookies()
        }
        "extractorCheck" -> extractorCheck()
        "extractorUpdate" -> Engine.update(ctx)
        else -> throw AppException("NOT_FOUND", "Unknown action.")
    }

    private fun requireUrl(url: String): String {
        val clean = url.trim()
        if (!UrlExtractor.isValid(clean)) {
            throw AppException("INVALID_URL", "That doesn't look like a web link. Links start with https://")
        }
        return clean
    }

    private fun dependencies(): JSONObject {
        var version: String? = null
        var problem: String? = null
        try {
            Engine.ensureReady(ctx)
            version = Engine.version(ctx)
        } catch (e: AppException) {
            problem = e.message
        } catch (e: Exception) {
            problem = e.message ?: "The download engine is unavailable."
        }
        val ok = problem == null
        val appVersion = try {
            ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
        } catch (_: Exception) {
            "?"
        }
        val extractor = JSONObject().put("ok", ok).put("version", version ?: "unavailable")
        if (!ok) extractor.put("message", problem)
        return JSONObject()
            .put("backend", JSONObject().put("ok", true).put("version", "$appVersion (on-device)"))
            .put("python", JSONObject().put("ok", ok).put("version", "built in"))
            .put("ffmpeg", JSONObject().put("ok", ok).put("version", "built in"))
            .put("extractor", extractor)
    }

    private fun createJob(a: JSONObject): JSONObject {
        val url = requireUrl(a.optString("url"))
        val formatId = a.optString("format_id", "best").ifEmpty { "best" }
        val mode = if (formatId == "audio") "audio" else "best"
        val job = Downloads.enqueue(
            ctx, url, formatId, mode,
            outputFormat = a.optString("output_format").ifEmpty { null },
            title = a.optString("title").ifEmpty { null },
            thumbnail = a.optString("thumbnail").ifEmpty { null },
        )
        return JSONObject().put("job_id", job.id).put("status", job.status)
    }

    private fun batch(a: JSONObject): JSONObject {
        val urls = a.optJSONArray("urls") ?: JSONArray()
        val mode = if (a.optString("mode") == "audio") "audio" else "best"
        if (urls.length() == 0 || urls.length() > UrlExtractor.MAX_LINKS) {
            throw AppException("INVALID_REQUEST", "Add between 1 and ${UrlExtractor.MAX_LINKS} links.")
        }
        val items = JSONArray()
        var queued = 0
        val seen = HashSet<String>()
        for (i in 0 until urls.length()) {
            val url = urls.optString(i).trim()
            if (!seen.add(url)) continue
            val item = JSONObject().put("url", url)
            try {
                val job = Downloads.enqueue(ctx, requireUrl(url), if (mode == "audio") "audio" else "best", mode)
                item.put("ok", true).put("job_id", job.id).put("title", JSONObject.NULL).put("error", JSONObject.NULL)
                queued++
            } catch (e: AppException) {
                item.put("ok", false).put("job_id", JSONObject.NULL).put("title", JSONObject.NULL).put("error", e.message)
            }
            items.put(item)
        }
        return JSONObject().put("items", items).put("queued", queued).put("failed", items.length() - queued)
    }

    private fun history(limit: Int): JSONObject {
        val items = JSONArray()
        store.completed(limit.coerceIn(1, 200)).forEach { items.put(it.toHistoryJson(MediaSaver.exists(ctx, it.fileUri))) }
        return JSONObject().put("items", items)
    }

    private fun openFile(id: String): JSONObject {
        val job = store.get(id) ?: throw AppException("NOT_FOUND", "That download no longer exists.")
        if (!MediaSaver.exists(ctx, job.fileUri)) {
            throw AppException("FILE_MISSING", "The file was moved or deleted.")
        }
        val intent = Notifications.viewIntent(ctx, job)
            ?: throw AppException("FILE_MISSING", "The file was moved or deleted.")
        activity.runOnUiThread {
            try {
                activity.startActivity(intent)
            } catch (_: Exception) {
                Toast.makeText(activity, "No app found to open this file.", Toast.LENGTH_LONG).show()
            }
        }
        return JSONObject().put("ok", true)
    }

    private fun settings(): JSONObject {
        return JSONObject()
            .put("output_directory", "Downloads/${MediaSaver.FOLDER}")
            .put("allowed_source_domains", JSONArray().put("*"))
            .put("universal_mode", true)
            .put("max_parallel_jobs", DownloadService.MAX_PARALLEL)
            .put("share_mode", Prefs.shareMode(ctx))
            .put("share_quality", Prefs.shareQuality(ctx))
    }

    private fun cookies(): JSONObject {
        val f = Engine.cookieFile(ctx)
        val has = f.isFile && f.length() > 0
        return JSONObject().put("has_cookies", has).put("size_bytes", if (has) f.length() else 0)
    }

    private fun saveCookies(content: String): JSONObject {
        val text = content.trim()
        if (text.isEmpty()) throw AppException("INVALID_REQUEST", "The cookies text is empty.")
        if (text.length > 1_000_000) throw AppException("INVALID_REQUEST", "That cookies file is too large.")
        if (!text.contains('\t') && !text.startsWith("# Netscape")) {
            throw AppException("INVALID_REQUEST", "This doesn't look like a cookies.txt file (Netscape format).")
        }
        Engine.cookieFile(ctx).writeText(text + "\n")
        return cookies()
    }

    private fun extractorCheck(): JSONObject {
        val current = Engine.version(ctx)
        val latest = Engine.latestVersion().removePrefix("v")
        return JSONObject()
            .put("current", current)
            .put("latest", latest)
            .put("update_available", latest.isNotEmpty() && latest != current)
            .put("supported", true)
    }
}
