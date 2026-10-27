package com.digitaldownloader.app

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import java.io.File
import java.io.IOException

/** Moves a finished file from private working storage into the public Downloads folder. */
object MediaSaver {
    const val FOLDER = "DigitalDownloader"

    data class Saved(val uri: String, val name: String, val size: Long)

    fun mimeFor(name: String): String {
        val ext = name.substringAfterLast('.', "").lowercase()
        return when (ext) {
            "mp4", "m4v" -> "video/mp4"
            "mkv" -> "video/x-matroska"
            "webm" -> "video/webm"
            "m4a" -> "audio/mp4"
            "mp3" -> "audio/mpeg"
            "opus", "ogg" -> "audio/ogg"
            else -> MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
        }
    }

    fun save(ctx: Context, src: File): Saved {
        val name = src.name
        val mime = mimeFor(name)
        val size = src.length()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) saveScoped(ctx, src, name, mime, size) else saveLegacy(ctx, src, name, size)
    }

    private fun saveScoped(ctx: Context, src: File, name: String, mime: String, size: Long): Saved {
        val resolver = ctx.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/" + FOLDER)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IOException("Could not create the file in Downloads")
        try {
            resolver.openOutputStream(uri)?.use { out ->
                src.inputStream().use { it.copyTo(out) }
            } ?: throw IOException("Could not open the file in Downloads")
            val done = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
            resolver.update(uri, done, null, null)
        } catch (e: Exception) {
            try { resolver.delete(uri, null, null) } catch (_: Exception) {}
            throw e
        }
        return Saved(uri.toString(), displayName(ctx, uri) ?: name, size)
    }

    @Suppress("DEPRECATION")
    private fun saveLegacy(ctx: Context, src: File, name: String, size: Long): Saved {
        // Android 8 and 9: write to the public folder when we are allowed, otherwise keep it in the app's own folder.
        val publicDir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), FOLDER)
        val targetDir = if ((publicDir.exists() || publicDir.mkdirs()) && publicDir.canWrite()) {
            publicDir
        } else {
            File(ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: ctx.filesDir, FOLDER).also { it.mkdirs() }
        }
        var target = File(targetDir, name)
        var n = 1
        while (target.exists()) {
            target = File(targetDir, name.substringBeforeLast('.') + " ($n)." + name.substringAfterLast('.', ""))
            n++
        }
        src.copyTo(target)
        MediaScannerConnection.scanFile(ctx, arrayOf(target.absolutePath), null, null)
        return Saved(Uri.fromFile(target).toString(), target.name, size)
    }

    fun displayName(ctx: Context, uri: Uri): String? {
        return try {
            ctx.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        } catch (_: Exception) {
            null
        }
    }

    fun exists(ctx: Context, uriString: String?): Boolean {
        if (uriString.isNullOrEmpty()) return false
        return try {
            val uri = Uri.parse(uriString)
            if (uri.scheme == "file") {
                File(uri.path ?: return false).exists()
            } else {
                ctx.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns._ID), null, null, null)?.use { it.count > 0 } ?: false
            }
        } catch (_: Exception) {
            false
        }
    }
}
