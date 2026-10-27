package com.digitaldownloader.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.webkit.MimeTypeMap
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ProgressBar
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.webkit.WebViewAssetLoader

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar
    private lateinit var assetLoader: WebViewAssetLoader

    @Volatile
    private var pageLoaded = false

    /** Text (one or more links) waiting to be handed to the page. */
    @Volatile
    var pendingSharedText: String? = null

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { /* nothing to do either way */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        assetLoader = WebViewAssetLoader.Builder()
            .setDomain("appassets.androidplatform.net")
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/static/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        setupViews()
        handleIntent(intent)
        askForPermissionsOnce()
        Downloads.resume(this)

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

    override fun onResume() {
        super.onResume()
        // Downloads may have been added from the share sheet while the app was in the background.
        Downloads.resume(this)
    }

    private fun askForPermissionsOnce() {
        if (Prefs.permissionsAsked(this)) return
        val wanted = ArrayList<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            wanted.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED
        ) {
            wanted.add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
        Prefs.setPermissionsAsked(this)
        if (wanted.isNotEmpty()) permissionLauncher.launch(wanted.toTypedArray())
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupViews() {
        val rootLayout = FrameLayout(this)
        rootLayout.layoutParams = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT,
        )

        webView = WebView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
            setLayerType(View.LAYER_TYPE_HARDWARE, null)
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                // The page comes from the app's own assets through the asset loader: no file access needed.
                allowFileAccess = false
                allowContentAccess = false
                loadsImagesAutomatically = true
                mediaPlaybackRequiresUserGesture = true
                cacheMode = WebSettings.LOAD_DEFAULT
                useWideViewPort = true
                loadWithOverviewMode = true
            }

            addJavascriptInterface(
                WebAppInterface(this@MainActivity) { js -> runOnUiThread { evaluateJavascript(js, null) } },
                "AndroidBridge",
            )

            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                    val intercepted = assetLoader.shouldInterceptRequest(request.url)
                    if (intercepted != null) return intercepted

                    // Fallback for absolute /static/... paths used by the shared web UI.
                    try {
                        val path = request.url.path ?: return null
                        val cleanPath = path.removePrefix("/assets/").removePrefix("/static/").removePrefix("/")
                        for (candidate in listOf("static/$cleanPath", cleanPath)) {
                            try {
                                val stream = assets.open(candidate)
                                return WebResourceResponse(getMimeType(candidate), "UTF-8", stream)
                            } catch (_: Exception) {
                            }
                        }
                    } catch (_: Exception) {
                    }
                    return null
                }

                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                    progressBar.visibility = View.VISIBLE
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    progressBar.visibility = View.GONE
                    // On a cold start the page asks for the shared text itself (getSharedUrl).
                    pageLoaded = true
                }

                override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                    val target = request?.url?.toString() ?: return false
                    if (target.startsWith("https://appassets.androidplatform.net/")) return false
                    // Anything else (links inside the app) opens in the phone's browser.
                    return try {
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(target)))
                        true
                    } catch (_: Exception) {
                        true
                    }
                }
            }

            webChromeClient = object : WebChromeClient() {
                override fun onProgressChanged(view: WebView?, newProgress: Int) {
                    progressBar.progress = newProgress
                    if (newProgress >= 100) progressBar.visibility = View.GONE
                }
            }
        }

        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            layoutParams = FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, 8)
            max = 100
            visibility = View.GONE
        }

        rootLayout.addView(webView)
        rootLayout.addView(progressBar)
        setContentView(rootLayout)

        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html")
    }

    private fun handleIntent(intent: Intent?) {
        if (intent == null) return
        val shared = intent.getStringExtra(EXTRA_SHARED_TEXT)
        if (!shared.isNullOrBlank()) {
            pendingSharedText = shared
            intent.removeExtra(EXTRA_SHARED_TEXT)
            dispatchPendingText()
            return
        }
        if (intent.action == Intent.ACTION_VIEW) {
            val data = intent.data ?: return
            val link = data.getQueryParameter("url") ?: return
            if (UrlExtractor.isValid(link)) {
                pendingSharedText = link
                dispatchPendingText()
            }
        }
    }

    /** Warm start: the page is already running, so hand the text over right away. */
    private fun dispatchPendingText() {
        if (!pageLoaded || !::webView.isInitialized) return
        val text = pendingSharedText ?: return
        pendingSharedText = null
        val literal = org.json.JSONObject.quote(text)
        webView.post {
            webView.evaluateJavascript(
                "if (window.handleSharedUrl) { window.handleSharedUrl($literal); }",
                null,
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

    companion object {
        const val EXTRA_SHARED_TEXT = "com.digitaldownloader.app.SHARED_TEXT"
    }
}
