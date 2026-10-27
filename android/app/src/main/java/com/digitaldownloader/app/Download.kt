package com.digitaldownloader.app

import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** One row of the download queue. Field names mirror the desktop job snapshot the UI already understands. */
data class Download(
    val id: String,
    val url: String,
    val title: String,
    val thumbnail: String?,
    val formatId: String,
    val mode: String,
    val outputFormat: String?,
    val status: String,
    val stage: String,
    val progress: Double,
    val downloadedBytes: Long,
    val totalBytes: Long,
    val speedBps: Double,
    val etaSeconds: Long,
    val filename: String?,
    val fileUri: String?,
    val fileSize: Long,
    val errorCode: String?,
    val errorMessage: String?,
    val createdAt: Long,
    val startedAt: Long,
    val completedAt: Long,
) {
    val isActive: Boolean get() = status == STATUS_QUEUED || status == STATUS_DOWNLOADING || status == STATUS_PROCESSING
    val isFinished: Boolean get() = !isActive

    fun toJson(): JSONObject {
        val o = JSONObject()
        o.put("job_id", id)
        o.put("id", id)
        o.put("url", url)
        o.put("status", status)
        o.put("title", title)
        o.put("thumbnail", thumbnail ?: JSONObject.NULL)
        o.put("progress", progress)
        o.put("stage", stage)
        o.put("downloaded_bytes", if (downloadedBytes > 0) downloadedBytes else JSONObject.NULL)
        o.put("total_bytes", if (totalBytes > 0) totalBytes else JSONObject.NULL)
        o.put("speed_bps", if (speedBps > 0) speedBps else JSONObject.NULL)
        o.put("eta_seconds", if (etaSeconds >= 0) etaSeconds else JSONObject.NULL)
        o.put("filename", filename ?: JSONObject.NULL)
        o.put("file_size", if (fileSize > 0) fileSize else JSONObject.NULL)
        if (errorCode != null) {
            o.put("error", JSONObject().put("code", errorCode).put("message", errorMessage ?: ""))
        } else {
            o.put("error", JSONObject.NULL)
        }
        o.put("created_at", iso(createdAt))
        o.put("started_at", iso(startedAt))
        o.put("completed_at", iso(completedAt))
        return o
    }

    /** Shape used by the "recent downloads" list. */
    fun toHistoryJson(fileExists: Boolean): JSONObject {
        val o = JSONObject()
        o.put("id", id)
        o.put("url", url)
        o.put("title", title)
        o.put("filename", filename ?: JSONObject.NULL)
        o.put("file_size", if (fileSize > 0) fileSize else JSONObject.NULL)
        o.put("source", sourceLabel(url))
        o.put("format_label", if (mode == "audio") "Audio" else "Video")
        o.put("completed_at", iso(completedAt))
        o.put("file_exists", fileExists)
        return o
    }

    companion object {
        const val STATUS_QUEUED = "queued"
        const val STATUS_DOWNLOADING = "downloading"
        const val STATUS_PROCESSING = "processing"
        const val STATUS_COMPLETED = "completed"
        const val STATUS_FAILED = "failed"
        const val STATUS_CANCELLED = "cancelled"

        private fun iso(millis: Long): Any {
            if (millis <= 0) return JSONObject.NULL
            val f = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
            f.timeZone = TimeZone.getTimeZone("UTC")
            return f.format(Date(millis))
        }

        fun sourceLabel(url: String): String {
            return try {
                val host = java.net.URI(url).host?.lowercase()?.removePrefix("www.") ?: return "Web"
                host
            } catch (_: Exception) {
                "Web"
            }
        }
    }
}
