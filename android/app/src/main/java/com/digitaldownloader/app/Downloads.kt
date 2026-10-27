package com.digitaldownloader.app

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import java.util.UUID

/** Entry points used by the web bridge, the share receiver and the notifications. */
object Downloads {

    fun enqueue(
        ctx: Context,
        url: String,
        formatId: String,
        mode: String,
        outputFormat: String? = null,
        title: String? = null,
        thumbnail: String? = null,
    ): Download {
        if (!UrlExtractor.isValid(url)) {
            throw AppException("INVALID_URL", "That doesn't look like a web link. Links start with https://")
        }
        val job = Download(
            id = UUID.randomUUID().toString(),
            url = url,
            title = title?.takeIf { it.isNotBlank() } ?: url,
            thumbnail = thumbnail?.takeIf { it.startsWith("https://") },
            formatId = formatId,
            mode = mode,
            outputFormat = outputFormat?.takeIf { it.isNotBlank() },
            status = Download.STATUS_QUEUED,
            stage = "Waiting to start",
            progress = 0.0,
            downloadedBytes = 0,
            totalBytes = 0,
            speedBps = 0.0,
            etaSeconds = -1,
            filename = null,
            fileUri = null,
            fileSize = 0,
            errorCode = null,
            errorMessage = null,
            createdAt = System.currentTimeMillis(),
            startedAt = 0,
            completedAt = 0,
        )
        DownloadStore.get(ctx).insert(job)
        startService(ctx)
        return job
    }

    fun cancel(ctx: Context, id: String) {
        val service = DownloadService.instance
        if (service != null) {
            service.cancelJob(id)
            return
        }
        val store = DownloadStore.get(ctx)
        val job = store.get(id) ?: throw AppException("NOT_FOUND", "That download no longer exists.")
        if (!job.isActive) return
        val v = ContentValues()
        v.put("status", Download.STATUS_CANCELLED)
        v.put("stage", "")
        v.put("completed", System.currentTimeMillis())
        store.update(id, v)
    }

    /** Starts a fresh download from a failed or cancelled one (same behaviour as the desktop app). */
    fun retry(ctx: Context, id: String): Download {
        val store = DownloadStore.get(ctx)
        val old = store.get(id) ?: throw AppException("NOT_FOUND", "That download no longer exists.")
        if (old.status != Download.STATUS_FAILED && old.status != Download.STATUS_CANCELLED) {
            throw AppException("NOT_RETRYABLE", "Only failed or cancelled downloads can be retried.")
        }
        val fresh = enqueue(
            ctx, old.url, old.formatId, old.mode, old.outputFormat,
            old.title.takeIf { it != old.url }, old.thumbnail,
        )
        store.delete(old.id)
        return fresh
    }

    /** Called when the app opens: pick up work left over from an earlier session. */
    fun resume(ctx: Context) {
        val store = DownloadStore.get(ctx)
        if (DownloadService.instance == null) store.resetInterrupted()
        if (store.queuedIds().isNotEmpty()) startService(ctx)
    }

    private fun startService(ctx: Context) {
        try {
            ContextCompat.startForegroundService(ctx, Intent(ctx, DownloadService::class.java))
        } catch (_: Exception) {
            // Android refused to start a background service (app not visible). The job stays queued
            // and starts the next time the app is opened.
        }
    }
}
