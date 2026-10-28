package com.digitaldownloader.app

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/** Persistent download queue (survives app restarts and process death). */
class DownloadStore private constructor(ctx: Context) : SQLiteOpenHelper(ctx, "downloads.db", null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE downloads (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                thumb TEXT,
                format_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                output_format TEXT,
                status TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT '',
                progress REAL NOT NULL DEFAULT 0,
                downloaded INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                speed REAL NOT NULL DEFAULT 0,
                eta INTEGER NOT NULL DEFAULT -1,
                filename TEXT,
                file_uri TEXT,
                file_size INTEGER NOT NULL DEFAULT 0,
                err_code TEXT,
                err_msg TEXT,
                created INTEGER NOT NULL,
                started INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX idx_downloads_status ON downloads(status)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Version 1 is the first schema; nothing to migrate yet.
    }

    @Synchronized
    fun insert(d: Download) {
        val v = ContentValues()
        v.put("id", d.id)
        v.put("url", d.url)
        v.put("title", d.title)
        v.put("thumb", d.thumbnail)
        v.put("format_id", d.formatId)
        v.put("mode", d.mode)
        v.put("output_format", d.outputFormat)
        v.put("status", d.status)
        v.put("stage", d.stage)
        v.put("created", d.createdAt)
        writableDatabase.insertOrThrow("downloads", null, v)
        prune()
    }

    @Synchronized
    fun update(id: String, values: ContentValues) {
        // A cancelled download stays cancelled: late progress or "back to the queue" writes from the worker
        // thread that was still shutting down must never bring it back to life.
        if (values.getAsString("status") == Download.STATUS_CANCELLED) {
            writableDatabase.update("downloads", values, "id = ?", arrayOf(id))
        } else {
            writableDatabase.update("downloads", values, "id = ? AND status != ?", arrayOf(id, Download.STATUS_CANCELLED))
        }
    }

    @Synchronized
    fun get(id: String): Download? {
        readableDatabase.query("downloads", null, "id = ?", arrayOf(id), null, null, null).use { c ->
            return if (c.moveToFirst()) read(c) else null
        }
    }

    @Synchronized
    fun list(limit: Int = 200): List<Download> {
        val out = ArrayList<Download>()
        readableDatabase.query("downloads", null, null, null, null, null, "created DESC", limit.toString()).use { c ->
            while (c.moveToNext()) out.add(read(c))
        }
        return out
    }

    @Synchronized
    fun completed(limit: Int): List<Download> {
        val out = ArrayList<Download>()
        readableDatabase.query(
            "downloads", null, "status = ?", arrayOf(Download.STATUS_COMPLETED),
            null, null, "completed DESC", limit.toString(),
        ).use { c ->
            while (c.moveToNext()) out.add(read(c))
        }
        return out
    }

    @Synchronized
    fun queuedIds(): List<String> {
        val out = ArrayList<String>()
        readableDatabase.query(
            "downloads", arrayOf("id"), "status = ?", arrayOf(Download.STATUS_QUEUED),
            null, null, "created ASC",
        ).use { c ->
            while (c.moveToNext()) out.add(c.getString(0))
        }
        return out
    }

    @Synchronized
    fun activeIds(): List<String> {
        val out = ArrayList<String>()
        readableDatabase.query(
            "downloads", arrayOf("id"), "status IN ('queued','downloading','processing')",
            null, null, null, "created ASC",
        ).use { c ->
            while (c.moveToNext()) out.add(c.getString(0))
        }
        return out
    }

    @Synchronized
    fun activeCount(): Int = activeIds().size

    /** Called when the service starts fresh: anything left "downloading" was interrupted. */
    @Synchronized
    fun resetInterrupted() {
        val v = ContentValues()
        v.put("status", Download.STATUS_QUEUED)
        v.put("stage", "")
        v.put("speed", 0.0)
        v.put("eta", -1)
        writableDatabase.update("downloads", v, "status IN ('downloading','processing')", null)
    }

    @Synchronized
    fun delete(id: String) {
        writableDatabase.delete("downloads", "id = ?", arrayOf(id))
    }

    private fun prune() {
        writableDatabase.execSQL(
            "DELETE FROM downloads WHERE status IN ('completed','failed','cancelled') AND id NOT IN " +
                "(SELECT id FROM downloads ORDER BY created DESC LIMIT $KEEP)",
        )
    }

    private fun read(c: Cursor): Download {
        fun s(name: String): String? = c.getString(c.getColumnIndexOrThrow(name))
        fun l(name: String): Long = c.getLong(c.getColumnIndexOrThrow(name))
        fun d(name: String): Double = c.getDouble(c.getColumnIndexOrThrow(name))
        return Download(
            id = s("id") ?: "",
            url = s("url") ?: "",
            title = s("title") ?: "",
            thumbnail = s("thumb"),
            formatId = s("format_id") ?: "best",
            mode = s("mode") ?: "best",
            outputFormat = s("output_format"),
            status = s("status") ?: Download.STATUS_FAILED,
            stage = s("stage") ?: "",
            progress = d("progress"),
            downloadedBytes = l("downloaded"),
            totalBytes = l("total"),
            speedBps = d("speed"),
            etaSeconds = l("eta"),
            filename = s("filename"),
            fileUri = s("file_uri"),
            fileSize = l("file_size"),
            errorCode = s("err_code"),
            errorMessage = s("err_msg"),
            createdAt = l("created"),
            startedAt = l("started"),
            completedAt = l("completed"),
        )
    }

    companion object {
        private const val KEEP = 200

        @Volatile
        private var instance: DownloadStore? = null

        fun get(ctx: Context): DownloadStore {
            return instance ?: synchronized(this) {
                instance ?: DownloadStore(ctx.applicationContext).also { instance = it }
            }
        }
    }
}
