# Proguard rules for Digital Downloader (minification is currently off; these keep the web bridge safe if it is enabled later).
-keepattributes JavascriptInterface
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.digitaldownloader.app.WebAppInterface { *; }
-keep class com.yausername.** { *; }
-keep class com.fasterxml.jackson.** { *; }
