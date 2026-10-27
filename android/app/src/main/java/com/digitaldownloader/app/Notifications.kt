package com.digitaldownloader.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.FileProvider
import java.io.File

object Notifications {
    private const val CHANNEL_PROGRESS = "downloads_progress"
    private const val CHANNEL_DONE = "downloads_done"
    const val SUMMARY_ID = 1001

    fun ensureChannels(ctx: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val progress = NotificationChannel(CHANNEL_PROGRESS, "Download progress", NotificationManager.IMPORTANCE_LOW)
        progress.description = "Shows running downloads"
        progress.setShowBadge(false)
        val done = NotificationChannel(CHANNEL_DONE, "Finished downloads", NotificationManager.IMPORTANCE_DEFAULT)
        done.description = "Tells you when a download is ready or has failed"
        nm.createNotificationChannel(progress)
        nm.createNotificationChannel(done)
    }

    private fun openApp(ctx: Context): PendingIntent {
        val intent = Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(ctx, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    /** The ongoing notification that keeps the download service alive. */
    fun summary(ctx: Context, running: Int, waiting: Int, percent: Int): Notification {
        val cancelAll = PendingIntent.getService(
            ctx, 1,
            Intent(ctx, DownloadService::class.java).setAction(DownloadService.ACTION_CANCEL_ALL),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val text = when {
            running == 0 && waiting == 0 -> "Getting ready…"
            waiting > 0 -> "$running running · $waiting waiting"
            else -> if (running == 1) "1 download running" else "$running downloads running"
        }
        val b = NotificationCompat.Builder(ctx, CHANNEL_PROGRESS)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Digital Downloader")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setContentIntent(openApp(ctx))
            .addAction(0, "Cancel all", cancelAll)
        if (running > 0 && percent in 0..100) b.setProgress(100, percent, false) else b.setProgress(0, 0, true)
        return b.build()
    }

    fun done(ctx: Context, job: Download) {
        val uri = job.fileUri
        val builder = NotificationCompat.Builder(ctx, CHANNEL_DONE)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle(job.title.ifBlank { "Download finished" })
            .setContentText("Saved to Downloads/${MediaSaver.FOLDER}")
            .setAutoCancel(true)
        val viewIntent = viewIntent(ctx, job)
        builder.setContentIntent(
            if (viewIntent != null) {
                PendingIntent.getActivity(ctx, job.id.hashCode(), viewIntent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            } else {
                openApp(ctx)
            },
        )
        if (uri == null) builder.setContentIntent(openApp(ctx))
        notify(ctx, job.id.hashCode(), builder.build())
    }

    fun failed(ctx: Context, job: Download, message: String) {
        val b = NotificationCompat.Builder(ctx, CHANNEL_DONE)
            .setSmallIcon(android.R.drawable.stat_notify_error)
            .setContentTitle("Download failed")
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText("${job.title.ifBlank { job.url }}\n$message"))
            .setAutoCancel(true)
            .setContentIntent(openApp(ctx))
        notify(ctx, job.id.hashCode(), b.build())
    }

    fun updateSummary(ctx: Context, running: Int, waiting: Int, percent: Int) {
        notify(ctx, SUMMARY_ID, summary(ctx, running, waiting, percent))
    }

    fun viewIntent(ctx: Context, job: Download): Intent? {
        val raw = job.fileUri ?: return null
        val uri = Uri.parse(raw)
        val shareUri = if (uri.scheme == "file") {
            try {
                FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", File(uri.path ?: return null))
            } catch (_: Exception) {
                return null
            }
        } else {
            uri
        }
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(shareUri, MediaSaver.mimeFor(job.filename ?: ""))
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
    }

    private fun notify(ctx: Context, id: Int, n: Notification) {
        try {
            val nm = NotificationManagerCompat.from(ctx)
            if (nm.areNotificationsEnabled()) nm.notify(id, n)
        } catch (_: SecurityException) {
            // Notification permission denied: downloads keep working without notifications.
        }
    }
}
