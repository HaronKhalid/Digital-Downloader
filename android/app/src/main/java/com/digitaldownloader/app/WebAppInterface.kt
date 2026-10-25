package com.digitaldownloader.app

import android.app.DownloadManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.webkit.JavascriptInterface
import android.widget.Toast
import androidx.core.content.FileProvider
import java.io.File
import java.io.FileOutputStream
import java.util.Base64

class WebAppInterface(private val activity: MainActivity) {

    private val prefs = activity.getSharedPreferences("digitaldownloader_prefs", Context.MODE_PRIVATE)

    @JavascriptInterface
    fun isAndroidApp(): Boolean = true

    @JavascriptInterface
    fun getBackendUrl(): String {
        return prefs.getString("backend_url", "http://10.0.2.2:8000") ?: "http://10.0.2.2:8000"
    }

    @JavascriptInterface
    fun setBackendUrl(url: String) {
        prefs.edit().putString("backend_url", url.trim()).apply()
    }

    @JavascriptInterface
    fun getSharedUrl(): String? {
        val url = activity.pendingSharedUrl
        activity.pendingSharedUrl = null
        return url
    }

    @JavascriptInterface
    fun showToast(message: String) {
        activity.runOnUiThread {
            Toast.makeText(activity, message, Toast.LENGTH_SHORT).show()
        }
    }

    @JavascriptInterface
    fun copyToClipboard(text: String) {
        activity.runOnUiThread {
            val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val clip = ClipData.newPlainText("Digital Downloader", text)
            clipboard.setPrimaryClip(clip)
            Toast.makeText(activity, "Copied to clipboard", Toast.LENGTH_SHORT).show()
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
        } catch (_: Exception) {}
    }

    @JavascriptInterface
    fun downloadUrlViaSystem(url: String, filename: String, mimeType: String): Boolean {
        return try {
            val dm = activity.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            val req = DownloadManager.Request(Uri.parse(url))
                .setTitle(filename)
                .setDescription("Downloading via Digital Downloader")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
            dm.enqueue(req)
            showToast("Download started in notification bar")
            true
        } catch (e: Exception) {
            showToast("Download error: ${e.message}")
            false
        }
    }

    @JavascriptInterface
    fun openFile(filePath: String) {
        try {
            val file = File(filePath)
            val uri = if (file.exists()) {
                FileProvider.getUriForFile(activity, "${activity.packageName}.fileprovider", file)
            } else {
                Uri.parse(filePath)
            }

            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, activity.getMimeType(filePath))
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            activity.startActivity(intent)
        } catch (e: Exception) {
            showToast("Cannot open file: ${e.message}")
        }
    }

    @JavascriptInterface
    fun openDownloadsFolder() {
        try {
            val intent = Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            activity.startActivity(intent)
        } catch (_: Exception) {
            try {
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(Uri.parse(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).path), "*/*")
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                activity.startActivity(intent)
            } catch (e: Exception) {
                showToast("Cannot open downloads folder: ${e.message}")
            }
        }
    }
}
