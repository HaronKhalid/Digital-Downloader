package com.digitaldownloader.app

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast

/**
 * Receives links shared from other apps (YouTube, Instagram, TikTok, browsers...).
 * In "background" mode the links go straight into the download queue and the user stays where they were.
 */
class ShareReceiverActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handle(intent)
        finish()
    }

    private fun handle(intent: Intent?) {
        if (intent == null || intent.action != Intent.ACTION_SEND) return
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)
            ?: intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
        val links = UrlExtractor.extract(text)
        if (links.isEmpty()) {
            Toast.makeText(this, "No web link found in what you shared.", Toast.LENGTH_LONG).show()
            return
        }

        if (Prefs.shareMode(this) == "open") {
            val open = Intent(this, MainActivity::class.java)
                .putExtra(MainActivity.EXTRA_SHARED_TEXT, links.joinToString(" "))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            startActivity(open)
            return
        }

        val mode = Prefs.shareQuality(this)
        var added = 0
        var firstError: String? = null
        for (link in links) {
            try {
                Downloads.enqueue(this, link, formatId = if (mode == "audio") "audio" else "best", mode = mode)
                added++
            } catch (e: AppException) {
                if (firstError == null) firstError = e.message
            } catch (e: Exception) {
                if (firstError == null) firstError = "Couldn't add this link."
            }
        }
        val message = when {
            added == 0 -> firstError ?: "Couldn't add this link."
            added == 1 -> "Added to Digital Downloader · downloading in the background"
            else -> "Added $added links to Digital Downloader"
        }
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }
}
