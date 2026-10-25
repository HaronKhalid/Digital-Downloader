# Proguard rules for Digital Downloader Android App
-keepattributes JavascriptInterface
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.digitaldownloader.app.WebAppInterface { *; }
-keep class com.linkfetch.app.WebAppInterface { *; }
