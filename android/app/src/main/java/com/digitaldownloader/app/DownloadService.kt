package com.digitaldownloader.app

import android.app.Service
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

/**
 * Runs the download queue in the foreground so downloads continue when the app is closed.
 * Up to [MAX_PARALLEL] downloads run at once; the rest wait their turn.
 */
class DownloadService : Service() {

    private lateinit var store: DownloadStore
    private lateinit var executor: ThreadPoolExecutor
    private var wakeLock: PowerManager.WakeLock? = null

    private val scheduled = ConcurrentHashMap.newKeySet<String>()
    private val cancelRequested = ConcurrentHashMap.newKeySet<String>()
    private val percentById = ConcurrentHashMap<String, Int>()

    @Volatile
    private var lastStartId = 0

    @Volatile
    private var lastNotify = 0L

    override fun onCreate() {
        super.onCreate()
        store = DownloadStore.get(this)
        Notifications.ensureChannels(this)
        executor = ThreadPoolExecutor(MAX_PARALLEL, MAX_PARALLEL, 30, TimeUnit.SECONDS, LinkedBlockingQueue())
        instance = this
        // A fresh service means nothing is running: anything left "downloading" was interrupted.
        store.resetInterrupted()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        lastStartId = startId
        if (!startAsForeground()) {
            stopSelf()
            return START_NOT_STICKY
        }
        acquireWakeLock()
        when (intent?.action) {
            ACTION_CANCEL_ALL -> cancelAll()
            ACTION_CANCEL -> intent.getStringExtra(EXTRA_ID)?.let { cancelJob(it) }
        }
        scheduleQueued()
        if (store.activeCount() == 0) finishIfIdle()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        instance = null
        executor.shutdownNow()
        // Anything still marked as running goes back to the queue and resumes next time.
        store.resetInterrupted()
        releaseWakeLock()
        super.onDestroy()
    }

    // ---------------------------------------------------------------- scheduling

    private fun startAsForeground(): Boolean {
        return try {
            val n = Notifications.summary(this, 0, store.activeCount(), 0)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(Notifications.SUMMARY_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            } else {
                startForeground(Notifications.SUMMARY_ID, n)
            }
            true
        } catch (_: Exception) {
            false
        }
    }

    private fun scheduleQueued() {
        for (id in store.queuedIds()) {
            if (scheduled.add(id)) {
                try {
                    executor.execute {
                        try {
                            runJob(id)
                        } finally {
                            scheduled.remove(id)
                            percentById.remove(id)
                            onJobFinished()
                        }
                    }
                } catch (_: Exception) {
                    scheduled.remove(id)
                }
            }
        }
    }

    private fun onJobFinished() {
        refreshSummary(force = true)
        if (store.queuedIds().isNotEmpty()) scheduleQueued()
        if (store.activeCount() == 0) finishIfIdle()
    }

    private fun finishIfIdle() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf(lastStartId)
    }

    private fun refreshSummary(force: Boolean) {
        val now = System.currentTimeMillis()
        if (!force && now - lastNotify < 1000) return
        lastNotify = now
        val active = store.activeIds().mapNotNull { store.get(it) }
        val running = active.count { it.status != Download.STATUS_QUEUED }
        val waiting = active.count { it.status == Download.STATUS_QUEUED }
        val percents = percentById.values
        val avg = if (percents.isEmpty()) 0 else percents.sum() / percents.size
        Notifications.updateSummary(this, running, waiting, avg)
    }

    // ---------------------------------------------------------------- cancel

    fun cancelJob(id: String) {
        val job = store.get(id) ?: return
        if (!job.isActive) return
        cancelRequested.add(id)
        val v = ContentValues()
        v.put("status", Download.STATUS_CANCELLED)
        v.put("stage", "")
        v.put("speed", 0.0)
        v.put("eta", -1)
        v.put("completed", System.currentTimeMillis())
        store.update(id, v)
        if (job.status != Download.STATUS_QUEUED) YoutubeDL.destroyProcessById(id)
        refreshSummary(force = true)
        if (store.activeCount() == 0) finishIfIdle()
    }

    private fun cancelAll() {
        for (id in store.activeIds()) cancelJob(id)
    }

    // ---------------------------------------------------------------- one download

    private class Tracker {
        var streams = 1
        var streamIndex = 0
        var lastSize = 0L
        var doneBytes = 0L
        var lastWrite = 0L
        var titleKnown = false
        var processing = false
    }

    private fun runJob(id: String) {
        val job = store.get(id)
        if (job == null || job.status != Download.STATUS_QUEUED) {
            cancelRequested.remove(id)
            return
        }

        val work = File(getExternalFilesDir(null) ?: filesDir, "work/$id")
        work.mkdirs()
        val tracker = Tracker().apply { titleKnown = job.title.isNotBlank() && job.title != job.url }

        try {
            if (work.usableSpace < MIN_FREE_BYTES) {
                throw AppException("DISK_SPACE_LOW", "Your phone is almost out of storage space.")
            }
            val started = ContentValues()
            started.put("status", Download.STATUS_DOWNLOADING)
            started.put("stage", "Starting")
            started.put("started", System.currentTimeMillis())
            store.update(id, started)
            refreshSummary(force = true)

            Engine.ensureReady(this)
            val request = Engine.downloadRequest(this, job, work)
            val callback: (Float, Long, String) -> Unit = { percent, eta, line -> onLine(id, tracker, percent, eta, line) }
            YoutubeDL.execute(request, id, callback)

            if (cancelRequested.contains(id)) throw YoutubeDL.CanceledException()

            val output = pickOutput(work)
                ?: throw AppException("DOWNLOAD_FAILED", "The download finished but no file was produced.")
            val saving = ContentValues()
            saving.put("status", Download.STATUS_PROCESSING)
            saving.put("stage", "Saving to Downloads")
            saving.put("progress", 99.0)
            saving.put("speed", 0.0)
            saving.put("eta", -1)
            store.update(id, saving)

            val saved = MediaSaver.save(this, output)
            val title = store.get(id)?.title?.takeIf { it.isNotBlank() && it != job.url }
                ?: output.nameWithoutExtension
            val done = ContentValues()
            done.put("status", Download.STATUS_COMPLETED)
            done.put("stage", "")
            done.put("progress", 100.0)
            done.put("speed", 0.0)
            done.put("eta", -1)
            done.put("title", title)
            done.put("filename", saved.name)
            done.put("file_uri", saved.uri)
            done.put("file_size", saved.size)
            done.put("completed", System.currentTimeMillis())
            store.update(id, done)
            store.get(id)?.let { Notifications.done(this, it) }
        } catch (e: YoutubeDL.CanceledException) {
            markCancelled(id)
        } catch (e: InterruptedException) {
            // The service is being stopped: leave the job queued so it resumes later.
            val back = ContentValues()
            back.put("status", Download.STATUS_QUEUED)
            back.put("stage", "")
            store.update(id, back)
            Thread.currentThread().interrupt()
            return
        } catch (e: AppException) {
            fail(id, e)
        } catch (e: YoutubeDLException) {
            if (cancelRequested.contains(id)) markCancelled(id) else fail(id, AppErrors.fromEngine(e.message))
        } catch (e: Exception) {
            if (cancelRequested.contains(id)) {
                markCancelled(id)
            } else {
                fail(id, AppException("DOWNLOAD_FAILED", e.message?.take(200) ?: "The download failed."))
            }
        } finally {
            cancelRequested.remove(id)
            work.deleteRecursively()
        }
    }

    private fun markCancelled(id: String) {
        val v = ContentValues()
        v.put("status", Download.STATUS_CANCELLED)
        v.put("stage", "")
        v.put("speed", 0.0)
        v.put("eta", -1)
        v.put("completed", System.currentTimeMillis())
        store.update(id, v)
    }

    private fun fail(id: String, error: AppException) {
        val v = ContentValues()
        v.put("status", Download.STATUS_FAILED)
        v.put("stage", "")
        v.put("speed", 0.0)
        v.put("eta", -1)
        v.put("err_code", error.code)
        v.put("err_msg", error.message)
        v.put("completed", System.currentTimeMillis())
        store.update(id, v)
        store.get(id)?.let { Notifications.failed(this, it, error.message) }
    }

    private fun pickOutput(dir: File): File? {
        val skip = listOf(".part", ".ytdl", ".temp", ".tmp", ".jpg", ".jpeg", ".png", ".webp", ".json", ".vtt", ".srt")
        return dir.listFiles()
            ?.filter { it.isFile && skip.none { ext -> it.name.endsWith(ext, ignoreCase = true) } }
            ?.maxByOrNull { it.length() }
    }

    private fun onLine(id: String, t: Tracker, percent: Float, eta: Long, line: String) {
        if (cancelRequested.contains(id)) return
        val v = ContentValues()
        var changed = false

        if (line.contains("format(s):")) {
            val ids = line.substringAfter("format(s):").trim()
            if (ids.isNotEmpty()) t.streams = ids.split("+").size.coerceAtLeast(1)
        }
        if (line.startsWith("[download] Destination:")) {
            t.streamIndex += 1
            t.doneBytes += t.lastSize
            t.lastSize = 0
            if (!t.titleKnown) {
                val name = line.substringAfter("Destination:").trim().substringAfterLast('/')
                val base = name.substringBeforeLast('.', name)
                if (base.isNotBlank()) {
                    v.put("title", base)
                    t.titleKnown = true
                    changed = true
                }
            }
        }

        val processingStage = when {
            line.startsWith("[Merger]") -> "Merging video and audio"
            line.startsWith("[ExtractAudio]") -> "Converting audio"
            line.startsWith("[VideoConvertor]") || line.startsWith("[VideoRemuxer]") -> "Converting video"
            line.startsWith("[Metadata]") || line.startsWith("[EmbedThumbnail]") || line.startsWith("[Fixup") -> "Finishing"
            else -> null
        }
        if (processingStage != null) {
            t.processing = true
            v.put("status", Download.STATUS_PROCESSING)
            v.put("stage", processingStage)
            v.put("speed", 0.0)
            v.put("eta", -1)
            v.put("progress", 99.0)
            changed = true
        } else if (!t.processing) {
            val size = parseSize(line)
            if (size > 0) t.lastSize = size
            val speed = parseSpeed(line)
            if (percent >= 0f && line.startsWith("[download]")) {
                val streamIdx = (t.streamIndex - 1).coerceAtLeast(0)
                val overall = ((streamIdx + percent / 100.0) / t.streams.coerceAtLeast(1) * 100.0).coerceIn(0.0, 99.0)
                v.put("progress", overall)
                v.put("stage", if (t.streams > 1) "Downloading part ${streamIdx + 1} of ${t.streams}" else "Downloading")
                v.put("downloaded", t.doneBytes + (t.lastSize * percent / 100.0).toLong())
                v.put("total", t.doneBytes + t.lastSize)
                if (speed > 0) v.put("speed", speed)
                v.put("eta", if (eta >= 0) eta else -1L)
                percentById[id] = overall.toInt()
                changed = true
            }
        }

        if (!changed) return
        val now = System.currentTimeMillis()
        // Stage changes are written right away; plain progress ticks at most every 600 ms.
        if (v.containsKey("status") || now - t.lastWrite >= 600) {
            t.lastWrite = now
            store.update(id, v)
            refreshSummary(force = false)
        }
    }

    private fun parseSize(line: String): Long {
        val m = SIZE.find(line) ?: return 0
        return toBytes(m.groupValues[1], m.groupValues[2])
    }

    private fun parseSpeed(line: String): Double {
        val m = SPEED.find(line) ?: return 0.0
        return toBytes(m.groupValues[1], m.groupValues[2]).toDouble()
    }

    private fun toBytes(number: String, unit: String): Long {
        val n = number.toDoubleOrNull() ?: return 0
        val factor = when (unit.uppercase().removeSuffix("B").removeSuffix("I")) {
            "K" -> 1024.0
            "M" -> 1024.0 * 1024
            "G" -> 1024.0 * 1024 * 1024
            "T" -> 1024.0 * 1024 * 1024 * 1024
            else -> 1.0
        }
        return (n * factor).toLong()
    }

    // ---------------------------------------------------------------- wake lock

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DigitalDownloader:downloads").apply {
                acquire(WAKE_LOCK_MAX_MS)
            }
        } catch (_: Exception) {
            // Downloads still work; the phone may just sleep sooner.
        }
    }

    private fun releaseWakeLock() {
        try {
            if (wakeLock?.isHeld == true) wakeLock?.release()
        } catch (_: Exception) {
        }
        wakeLock = null
    }

    companion object {
        const val ACTION_CANCEL = "com.digitaldownloader.app.CANCEL"
        const val ACTION_CANCEL_ALL = "com.digitaldownloader.app.CANCEL_ALL"
        const val EXTRA_ID = "id"
        const val MAX_PARALLEL = 3

        private const val MIN_FREE_BYTES = 50L * 1024 * 1024
        private const val WAKE_LOCK_MAX_MS = 6L * 60 * 60 * 1000

        private val SIZE = Regex("of\\s+~?\\s*([0-9.]+)\\s*([KMGT]?i?B)")
        private val SPEED = Regex("at\\s+([0-9.]+)\\s*([KMGT]?i?B)/s")

        @Volatile
        var instance: DownloadService? = null
            private set
    }
}
