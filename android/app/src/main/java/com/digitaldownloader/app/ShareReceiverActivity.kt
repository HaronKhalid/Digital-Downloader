package com.digitaldownloader.app

import android.app.Activity
import android.app.Dialog
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowManager
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast

/**
 * Receives links shared from other apps (YouTube, Instagram, TikTok, browsers...).
 *
 *  - "ask" (default): a small sheet appears over the other app so you pick quality and format, then it downloads.
 *  - "background": the link is queued at once with your saved quality.
 *  - "open": the full app opens with the link so you can inspect it first.
 */
class ShareReceiverActivity : Activity() {

    private class Choice(val label: String, val formatId: String)

    private val navy = Color.parseColor("#0B1226")
    private val navyLight = Color.parseColor("#151D36")
    private val gold = Color.parseColor("#D4AF37")
    private val muted = Color.parseColor("#A7ADBD")

    private val videoQualities = listOf(
        Choice("Best quality", "best"),
        Choice("1080p", "v1080"),
        Choice("720p", "v720"),
        Choice("480p", "v480"),
        Choice("360p", "v360"),
    )
    private val audioChoice = Choice("Audio only", "audio")
    private val videoFormats = listOf("MP4" to "mp4", "MKV" to "mkv", "WEBM" to "webm")
    private val audioFormats = listOf("M4A" to "m4a", "MP3" to "mp3", "OPUS" to "opus")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val links = linksFrom(intent)
        if (links.isEmpty()) {
            Toast.makeText(this, "No web link found in what you shared.", Toast.LENGTH_LONG).show()
            finish()
            return
        }
        when (Prefs.shareMode(this)) {
            "open" -> {
                openInApp(links)
                finish()
            }
            "background" -> {
                val mode = Prefs.shareQuality(this)
                enqueueAll(links, if (mode == "audio") "audio" else "best", mode, null)
                finish()
            }
            else -> showSheet(links)
        }
    }

    private fun linksFrom(intent: Intent?): List<String> {
        if (intent == null || intent.action != Intent.ACTION_SEND) return emptyList()
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)
            ?: intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
        return UrlExtractor.extract(text)
    }

    private fun openInApp(links: List<String>) {
        val open = Intent(this, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_SHARED_TEXT, links.joinToString(" "))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        startActivity(open)
    }

    private fun enqueueAll(links: List<String>, formatId: String, mode: String, outputFormat: String?) {
        var added = 0
        var firstError: String? = null
        for (link in links) {
            try {
                Downloads.enqueue(this, link, formatId = formatId, mode = mode, outputFormat = outputFormat)
                added++
            } catch (e: AppException) {
                if (firstError == null) firstError = e.message
            } catch (e: Exception) {
                if (firstError == null) firstError = "Couldn't add this link."
            }
        }
        val message = when {
            added == 0 -> firstError ?: "Couldn't add this link."
            added == 1 -> "Downloading in the background · see Digital Downloader"
            else -> "Added $added links to Digital Downloader"
        }
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    // ---------------------------------------------------------------- the sheet

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun label(text: String, size: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        this.text = text
        textSize = size
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    private fun spinner(items: List<String>): Spinner {
        val adapter = object : ArrayAdapter<String>(this, android.R.layout.simple_spinner_item, items) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup): View =
                (super.getView(position, convertView, parent) as TextView).also {
                    it.setTextColor(Color.WHITE)
                    it.setPadding(dp(12), dp(10), dp(12), dp(10))
                }

            override fun getDropDownView(position: Int, convertView: View?, parent: ViewGroup): View =
                (super.getDropDownView(position, convertView, parent) as TextView).also {
                    it.setTextColor(Color.WHITE)
                    it.setBackgroundColor(navyLight)
                    it.setPadding(dp(16), dp(14), dp(16), dp(14))
                }
        }
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        return Spinner(this).apply {
            this.adapter = adapter
            background = GradientDrawable().apply {
                setColor(navyLight)
                cornerRadius = dp(10).toFloat()
                setStroke(dp(1), Color.parseColor("#2A3350"))
            }
            setPopupBackgroundDrawable(ColorDrawable(navyLight))
        }
    }

    private fun row(title: String, spinner: Spinner) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(0, dp(10), 0, 0)
        addView(label(title, 12f, muted))
        addView(spinner, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(4) })
    }

    private fun button(text: String, primary: Boolean) = Button(this).apply {
        this.text = text
        isAllCaps = false
        setTextColor(if (primary) Color.parseColor("#1A1405") else Color.WHITE)
        background = GradientDrawable().apply {
            setColor(if (primary) gold else navyLight)
            cornerRadius = dp(12).toFloat()
        }
        stateListAnimator = null
    }

    private fun showSheet(links: List<String>) {
        val dialog = Dialog(this)
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)

        val qualitySpinner = spinner((videoQualities + audioChoice).map { it.label })
        val formatSpinner = spinner(videoFormats.map { it.first })

        fun syncFormats() {
            val audio = qualitySpinner.selectedItemPosition == videoQualities.size
            val names = (if (audio) audioFormats else videoFormats).map { it.first }
            @Suppress("UNCHECKED_CAST")
            val adapter = formatSpinner.adapter as ArrayAdapter<String>
            adapter.clear()
            adapter.addAll(names)
            adapter.notifyDataSetChanged()
            formatSpinner.setSelection(0)
        }
        qualitySpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, position: Int, id: Long) = syncFormats()
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        val first = links.first()
        val heading = if (links.size == 1) Download.sourceLabel(first) else "${links.size} links"
        val shown = if (links.size == 1) first else links.joinToString("\n") { it }

        val download = button(if (links.size == 1) "Download" else "Download all", true)
        val more = button("More options in app", false)
        val cancel = button("Cancel", false)

        val sheet = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(18), dp(20), dp(16))
            background = GradientDrawable().apply {
                setColor(navy)
                cornerRadii = floatArrayOf(dp(20).toFloat(), dp(20).toFloat(), dp(20).toFloat(), dp(20).toFloat(), 0f, 0f, 0f, 0f)
            }
            addView(label("Download from $heading", 18f, Color.WHITE, bold = true))
            addView(label(shown, 12f, muted).apply {
                maxLines = 2
                ellipsize = android.text.TextUtils.TruncateAt.MIDDLE
                setPadding(0, dp(4), 0, dp(6))
            })
            addView(row("Quality", qualitySpinner))
            addView(row("Save as", formatSpinner))
            addView(download, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(50)).apply { topMargin = dp(18) })
            addView(LinearLayout(this@ShareReceiverActivity).apply {
                orientation = LinearLayout.HORIZONTAL
                addView(more, LinearLayout.LayoutParams(0, dp(46), 1.6f).apply { rightMargin = dp(8) })
                addView(cancel, LinearLayout.LayoutParams(0, dp(46), 1f))
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(8) })
        }

        download.setOnClickListener {
            val audio = qualitySpinner.selectedItemPosition == videoQualities.size
            val choice = if (audio) audioChoice else videoQualities[qualitySpinner.selectedItemPosition]
            val formats = if (audio) audioFormats else videoFormats
            val output = formats.getOrNull(formatSpinner.selectedItemPosition)?.second
            // The first container of each list is what the engine produces anyway; only pass real choices.
            enqueueAll(links, choice.formatId, if (audio) "audio" else "best", output)
            dialog.dismiss()
        }
        more.setOnClickListener {
            openInApp(links)
            dialog.dismiss()
        }
        cancel.setOnClickListener { dialog.dismiss() }
        dialog.setOnDismissListener { finish() }

        dialog.setContentView(sheet)
        dialog.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            setLayout(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.WRAP_CONTENT)
            setGravity(Gravity.BOTTOM)
            setDimAmount(0.55f)
        }
        dialog.show()
    }
}
