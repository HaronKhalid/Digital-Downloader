package com.digitaldownloader.app

import android.content.Context

/** Small settings store shared by the app, the share receiver and the download service. */
object Prefs {
    private const val FILE = "digitaldownloader_prefs"

    private fun p(ctx: Context) = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** "background" = queue shared links silently, "open" = open the app with the link. */
    fun shareMode(ctx: Context): String = p(ctx).getString("share_mode", "background") ?: "background"

    fun setShareMode(ctx: Context, value: String) {
        if (value == "background" || value == "open") p(ctx).edit().putString("share_mode", value).apply()
    }

    /** "best" = best video that plays everywhere, "audio" = audio only. Used for background shares. */
    fun shareQuality(ctx: Context): String = p(ctx).getString("share_quality", "best") ?: "best"

    fun setShareQuality(ctx: Context, value: String) {
        if (value == "best" || value == "audio") p(ctx).edit().putString("share_quality", value).apply()
    }

    fun permissionsAsked(ctx: Context): Boolean = p(ctx).getBoolean("permissions_asked", false)

    fun setPermissionsAsked(ctx: Context) {
        p(ctx).edit().putBoolean("permissions_asked", true).apply()
    }
}
