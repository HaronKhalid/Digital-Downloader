package com.digitaldownloader.app

import android.content.Context
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Wraps the on-device yt-dlp + FFmpeg engine. Everything here may block: never call it on the UI thread. */
/** Like optString, but a JSON null counts as missing (Android's optString would return the text "null"). */
private fun JSONObject.text(key: String, fallback: String): String =
    if (isNull(key)) fallback else optString(key, fallback)

object Engine {
    @Volatile
    private var ready = false

    @Volatile
    var initError: String? = null
        private set

    @Volatile
    private var cachedVersion: String? = null

    private val watchdog = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "engine-watchdog").apply { isDaemon = true }
    }

    @Synchronized
    fun ensureReady(ctx: Context) {
        if (ready) return
        try {
            YoutubeDL.init(ctx.applicationContext)
            FFmpeg.init(ctx.applicationContext)
            ready = true
            initError = null
        } catch (e: Exception) {
            initError = e.message ?: "The download engine could not start."
            throw AppException("ENGINE_UNAVAILABLE", "The download engine could not start on this device.")
        }
    }

    fun isReady(): Boolean = ready

    fun cookieFile(ctx: Context): File = File(ctx.filesDir, "cookies.txt")

    private fun cookieArgs(ctx: Context, req: YoutubeDLRequest) {
        val f = cookieFile(ctx)
        if (f.isFile && f.length() > 0) req.addOption("--cookies", f.absolutePath)
    }

    /** yt-dlp version string, for example "2026.10.21". */
    fun version(ctx: Context): String {
        cachedVersion?.let { return it }
        ensureReady(ctx)
        val req = YoutubeDLRequest(emptyList<String>())
        req.addOption("--version")
        val out = YoutubeDL.execute(req, null, null).out.trim()
        cachedVersion = out.ifEmpty { "unknown" }
        return cachedVersion!!
    }

    /** Fetch information about one link and describe the choices the UI should offer. */
    fun analyze(ctx: Context, url: String): JSONObject {
        ensureReady(ctx)
        val processId = "probe-" + UUID.randomUUID()
        val req = YoutubeDLRequest(url)
        req.addOption("--dump-single-json")
        req.addOption("--no-playlist")
        req.addOption("--no-warnings")
        req.addOption("--socket-timeout", 20)
        cookieArgs(ctx, req)

        val timeout = watchdog.schedule(
            Runnable { YoutubeDL.destroyProcessById(processId) },
            PROBE_TIMEOUT_S,
            TimeUnit.SECONDS,
        )
        val raw: String = try {
            YoutubeDL.execute(req, processId, null).out
        } catch (e: YoutubeDL.CanceledException) {
            throw AppException("TIMEOUT", "The website took too long to answer. Try again.")
        } catch (e: YoutubeDLException) {
            throw AppErrors.fromEngine(e.message)
        } finally {
            timeout.cancel(false)
        }
        val info = try {
            JSONObject(raw.trim())
        } catch (e: Exception) {
            throw AppException("MEDIA_NOT_AVAILABLE", "Couldn't read any media from this link.")
        }
        if (info.text("_type", "") == "playlist") {
            throw AppException("PLAYLIST_NOT_SUPPORTED", "This link is a playlist. Playlists are coming in a later update; open a single video link for now.")
        }
        return describe(url, info)
    }

    private fun describe(url: String, info: JSONObject): JSONObject {
        val formats = info.optJSONArray("formats") ?: JSONArray()
        val heights = java.util.TreeMap<Int, Long>() // height -> biggest video-only size
        var bestAudio = 0L
        var anyVideo = false
        for (i in 0 until formats.length()) {
            val f = formats.optJSONObject(i) ?: continue
            val vcodec = f.text("vcodec", "none")
            val acodec = f.text("acodec", "none")
            val size = maxOf(f.optLong("filesize", 0L), f.optLong("filesize_approx", 0L))
            val height = f.optInt("height", 0)
            if (vcodec != "none" && vcodec.isNotEmpty() && height > 0) {
                anyVideo = true
                val previous = heights[height] ?: 0L
                heights[height] = maxOf(previous, size)
            }
            if (acodec != "none" && vcodec == "none" && size > bestAudio) bestAudio = size
        }
        val hasAudioStream = (0 until formats.length()).any {
            val f = formats.optJSONObject(it)
            f != null && f.text("acodec", "none") != "none"
        }

        val list = JSONArray()
        for (height in heights.descendingKeySet()) {
            val size = heights[height] ?: 0L
            val total = if (size > 0) size + bestAudio else 0L
            list.put(
                formatEntry(
                    id = "v$height", type = "video", container = "mp4", resolution = "${height}p",
                    hasAudio = true, size = total, label = "${height}p · MP4",
                ),
            )
        }
        if (!anyVideo && (info.has("url") || formats.length() > 0)) {
            val ext = info.text("ext", "mp4").ifEmpty { "mp4" }
            val size = maxOf(info.optLong("filesize", 0L), info.optLong("filesize_approx", 0L))
            list.put(
                formatEntry(
                    id = "best", type = "video", container = ext, resolution = null,
                    hasAudio = true, size = size, label = "Original · ${ext.uppercase()}",
                ),
            )
        }
        if (hasAudioStream || anyVideo) {
            list.put(
                formatEntry(
                    id = "audio", type = "audio", container = "m4a", resolution = null,
                    hasAudio = true, size = bestAudio, label = "Audio only · M4A",
                ),
            )
        }
        if (list.length() == 0) {
            throw AppException("MEDIA_NOT_AVAILABLE", "No downloadable media was found at this link.")
        }

        val out = JSONObject()
        out.put("source", "ytdlp")
        out.put("source_label", info.text("extractor_key", "Web media").ifEmpty { "Web media" })
        out.put("url", url)
        out.put("title", info.text("title", "").ifEmpty { Download.sourceLabel(url) })
        val duration = info.optDouble("duration", Double.NaN)
        out.put("duration", if (duration.isNaN()) JSONObject.NULL else duration.toLong())
        val thumb = info.text("thumbnail", "")
        out.put("thumbnail", if (thumb.startsWith("https://")) thumb else JSONObject.NULL)
        out.put("formats", list)
        return out
    }

    private fun formatEntry(
        id: String, type: String, container: String, resolution: String?,
        hasAudio: Boolean, size: Long, label: String,
    ): JSONObject {
        val o = JSONObject()
        o.put("id", id)
        o.put("type", type)
        o.put("container", container)
        o.put("resolution", resolution ?: JSONObject.NULL)
        o.put("has_audio", hasAudio)
        o.put("filesize", if (size > 0) size else JSONObject.NULL)
        o.put("filesize_approximate", true)
        o.put("label", label)
        return o
    }

    /** yt-dlp "-f" selector for one of the format ids produced by [describe] (or a batch mode). */
    fun selector(formatId: String, mode: String): String {
        if (mode == "audio" || formatId == "audio") return "ba[ext=m4a]/ba/b"
        if (formatId.startsWith("v")) {
            val h = formatId.removePrefix("v").toIntOrNull()
            if (h != null && h > 0) {
                return "bv*[height=$h][vcodec^=avc1]+ba[ext=m4a]/bv*[height=$h]+ba/b[height<=$h]/b"
            }
        }
        // Best quality that plays on every phone: prefer H.264 up to 1080p, otherwise the real best.
        return "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"
    }

    fun downloadRequest(ctx: Context, job: Download, workDir: File): YoutubeDLRequest {
        val req = YoutubeDLRequest(job.url)
        req.addOption("--no-playlist")
        req.addOption("--newline")
        req.addOption("--no-mtime")
        req.addOption("--retries", 5)
        req.addOption("--fragment-retries", 5)
        req.addOption("--socket-timeout", 30)
        req.addOption("--concurrent-fragments", 4)
        req.addOption("-o", workDir.absolutePath + "/%(title).120B.%(ext)s")
        req.addOption("-f", selector(job.formatId, job.mode))
        if (job.mode == "audio" || job.formatId == "audio") {
            req.addOption("-x")
            val fmt = job.outputFormat?.lowercase()
            req.addOption("--audio-format", if (fmt == "mp3" || fmt == "opus" || fmt == "m4a") fmt else "m4a")
        } else {
            val fmt = job.outputFormat?.lowercase()
            req.addOption("--merge-output-format", if (fmt == "mkv" || fmt == "webm" || fmt == "mp4") fmt else "mp4")
        }
        req.addOption("--embed-metadata")
        cookieArgs(ctx, req)
        return req
    }

    /** Asks GitHub for the newest yt-dlp release tag. */
    fun latestVersion(): String {
        val conn = URL("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest").openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = 10000
            conn.readTimeout = 15000
            conn.setRequestProperty("Accept", "application/vnd.github+json")
            conn.setRequestProperty("User-Agent", "DigitalDownloader")
            if (conn.responseCode != 200) throw AppException("UPDATE_CHECK_FAILED", "Couldn't check for updates right now.")
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            return JSONObject(body).optString("tag_name", "")
        } catch (e: AppException) {
            throw e
        } catch (e: Exception) {
            throw AppException("UPDATE_CHECK_FAILED", "Couldn't check for updates. Check your internet connection.")
        } finally {
            conn.disconnect()
        }
    }

    fun update(ctx: Context): JSONObject {
        ensureReady(ctx)
        val previous = version(ctx)
        try {
            YoutubeDL.updateYoutubeDL(ctx)
        } catch (e: Exception) {
            throw AppException("UPDATE_FAILED", "The update could not be installed. Try again later.")
        }
        cachedVersion = null
        val installed = version(ctx)
        return JSONObject().put("previous", previous).put("installed", installed)
    }

    private const val PROBE_TIMEOUT_S = 90L
}
