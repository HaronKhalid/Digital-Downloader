package com.digitaldownloader.app

/** An error with a stable code and a message that is safe to show to the user. */
class AppException(val code: String, override val message: String) : Exception(message)

object AppErrors {
    /** Turns raw yt-dlp output into a short code and a friendly message. */
    fun fromEngine(raw: String?): AppException {
        val text = (raw ?: "").trim()
        val lower = text.lowercase()
        return when {
            "unsupported url" in lower ->
                AppException("UNSUPPORTED_SOURCE", "This website or link type isn't supported.")
            "sign in" in lower || "log in" in lower || "login" in lower || "cookies" in lower ||
                "confirm you" in lower || "private" in lower ->
                AppException("AUTH_REQUIRED", "This link needs you to be signed in. Add your cookies in Settings and try again.")
            "video unavailable" in lower || "not available" in lower || "removed" in lower || "does not exist" in lower ->
                AppException("MEDIA_NOT_AVAILABLE", "This media isn't available any more or isn't public.")
            "429" in lower || "too many requests" in lower ->
                AppException("RATE_LIMITED", "The website is limiting requests. Wait a few minutes and try again.")
            "no space left" in lower ->
                AppException("DISK_SPACE_LOW", "Your phone is out of storage space.")
            "requested format is not available" in lower ->
                AppException("FORMAT_NOT_AVAILABLE", "That quality isn't available. Pick another one.")
            "unable to resolve" in lower || "network is unreachable" in lower || "timed out" in lower ||
                "connection" in lower || "temporary failure" in lower ->
                AppException("NETWORK", "Couldn't reach the website. Check your internet connection.")
            else -> {
                val last = text.lines().lastOrNull { it.contains("ERROR", ignoreCase = true) } ?: text
                val clean = last.removePrefix("ERROR:").trim().take(240)
                AppException("DOWNLOAD_FAILED", if (clean.isEmpty()) "The download failed." else clean)
            }
        }
    }
}
