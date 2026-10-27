package com.digitaldownloader.app

import java.net.URI

/** Finds web links inside shared text such as "Check this out https://youtu.be/abc". */
object UrlExtractor {
    const val MAX_LINKS = 25

    private val pattern = Regex("https?://[^\\s<>\"']+", RegexOption.IGNORE_CASE)

    fun extract(text: String?): List<String> {
        if (text.isNullOrBlank()) return emptyList()
        return pattern.findAll(text)
            .map { it.value.trimEnd('.', ',', ')', ']', '}', ';', '!') }
            .filter { isValid(it) }
            .distinct()
            .take(MAX_LINKS)
            .toList()
    }

    fun isValid(url: String): Boolean {
        return try {
            val uri = URI(url)
            val scheme = uri.scheme?.lowercase()
            (scheme == "http" || scheme == "https") && !uri.host.isNullOrBlank()
        } catch (_: Exception) {
            false
        }
    }
}
