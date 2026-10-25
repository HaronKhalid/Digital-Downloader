package com.digitaldownloader.app

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.MimeTypeMap
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ProgressBar
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.webkit.WebViewAssetLoader
import java.util.regex.Pattern

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar
    private lateinit var assetLoader: WebViewAssetLoader
    var pendingSharedUrl: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Setup Asset Loader to serve local assets securely via https://appassets.androidplatform.net/
        assetLoader = WebViewAssetLoader.Builder()
            .setDomain("appassets.androidplatform.net")
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/static/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        setupViews()
        handleIntent(intent)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupViews() {
        val rootLayout = android.widget.FrameLayout(this)
        rootLayout.layoutParams = android.widget.FrameLayout.LayoutParams(
            android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            android.widget.FrameLayout.LayoutParams.MATCH_PARENT
        )

        webView = WebView(this).apply {
            layoutParams = android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT
            )
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                allowFileAccess = true
                allowContentAccess = true
                loadsImagesAutomatically = true
                mediaPlaybackRequiresUserGesture = false
                cacheMode = WebSettings.LOAD_DEFAULT
                useWideViewPort = true
                loadWithOverviewMode = true
            }

            addJavascriptInterface(WebAppInterface(this@MainActivity), "AndroidBridge")

            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(
                    view: WebView,
                    request: WebResourceRequest
                ): WebResourceResponse? {
                    // 1. Try standard asset loader first
                    val intercepted = assetLoader.shouldInterceptRequest(request.url)
                    if (intercepted != null) return intercepted

                    // 2. Direct asset fallback for any /static/ or relative URLs
                    try {
                        val path = request.url.path ?: return null
                        val cleanPath = path.removePrefix("/assets/").removePrefix("/static/").removePrefix("/")
                        val candidates = listOf("static/$cleanPath", cleanPath)
                        for (candidate in candidates) {
                            try {
                                val stream = assets.open(candidate)
                                val mime = getMimeType(candidate)
                                return WebResourceResponse(mime, "UTF-8", stream)
                            } catch (_: Exception) {}
                        }
                    } catch (_: Exception) {}
                    return null
                }

                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                    progressBar.visibility = View.VISIBLE
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    progressBar.visibility = View.GONE
                    dispatchPendingUrl()
                }

                override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                    val targetUrl = request?.url?.toString() ?: return false
                    if (targetUrl.startsWith("https://appassets.androidplatform.net/") ||
                        targetUrl.startsWith("file:///android_asset/") ||
                        targetUrl.startsWith("http://127.0.0.1") ||
                        targetUrl.startsWith("http://localhost") ||
                        targetUrl.startsWith("http://10.0.2.2")) {
                        return false
                    }
                    // External links open in browser
                    return try {
                        val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse(targetUrl))
                        startActivity(browserIntent)
                        true
                    } catch (_: Exception) {
                        false
                    }
                }
            }

            webChromeClient = object : WebChromeClient() {
                override fun onProgressChanged(view: WebView?, newProgress: Int) {
                    progressBar.progress = newProgress
                    if (newProgress >= 100) {
                        progressBar.visibility = View.GONE
                    }
                }
            }
        }

        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            layoutParams = android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                8
            )
            max = 100
            visibility = View.GONE
        }

        rootLayout.addView(webView)
        rootLayout.addView(progressBar)
        setContentView(rootLayout)

        // Load the local app
        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html")
    }

    private fun handleIntent(intent: Intent?) {
        if (intent == null) return
        if (intent.action == Intent.ACTION_SEND && intent.type == "text/plain") {
            val sharedText = intent.getStringExtra(Intent.EXTRA_TEXT) ?: return
            val extractedUrl = extractUrl(sharedText) ?: sharedText.trim()
            pendingSharedUrl = extractedUrl
            dispatchPendingUrl()
        }
    }

    private fun extractUrl(text: String): String? {
        val pattern = Pattern.compile("https?://[^\\s]+")
        val matcher = pattern.matcher(text)
        return if (matcher.find()) matcher.group(0) else null
    }

    private fun dispatchPendingUrl() {
        val url = pendingSharedUrl ?: return
        val jsSafeUrl = url.replace("'", "\\'").replace("\"", "\\\"")
        webView.post {
            webView.evaluateJavascript(
                "if (window.handleSharedUrl) { window.handleSharedUrl('$jsSafeUrl'); } else { document.addEventListener('DOMContentLoaded', () => { if (window.handleSharedUrl) window.handleSharedUrl('$jsSafeUrl'); }); }",
                null
            )
        }
    }

    fun getMimeType(filePath: String): String {
        val lower = filePath.lowercase()
        return when {
            lower.endsWith(".css") -> "text/css"
            lower.endsWith(".js") || lower.endsWith(".mjs") -> "application/javascript"
            lower.endsWith(".html") || lower.endsWith(".htm") -> "text/html"
            lower.endsWith(".png") -> "image/png"
            lower.endsWith(".jpg") || lower.endsWith(".jpeg") -> "image/jpeg"
            lower.endsWith(".webp") -> "image/webp"
            lower.endsWith(".svg") -> "image/svg+xml"
            lower.endsWith(".ico") -> "image/x-icon"
            lower.endsWith(".json") -> "application/json"
            lower.endsWith(".woff2") -> "font/woff2"
            lower.endsWith(".woff") -> "font/woff"
            lower.endsWith(".ttf") -> "font/ttf"
            else -> {
                val ext = MimeTypeMap.getFileExtensionFromUrl(filePath)
                (if (ext != null) MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext.lowercase()) else null) ?: "*/*"
            }
        }
    }
}
