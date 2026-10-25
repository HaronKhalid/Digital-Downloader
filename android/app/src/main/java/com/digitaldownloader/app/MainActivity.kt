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
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
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
                    return assetLoader.shouldInterceptRequest(request.url)
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
        val ext = MimeTypeMap.getFileExtensionFromUrl(filePath)
        return if (ext != null) {
            MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext.lowercase()) ?: "*/*"
        } else {
            "*/*"
        }
    }
}
