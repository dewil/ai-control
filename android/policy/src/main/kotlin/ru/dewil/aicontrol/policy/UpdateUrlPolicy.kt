package ru.dewil.aicontrol.policy

import java.net.URI

object UpdateUrlPolicy {
    private fun exact(raw: String, path: String): Boolean = try {
        if (raw.length > 2048 || raw.any { it.code <= 32 || it.code == 127 }) false
        else URI(raw).let {
            it.scheme.equals("https", true) &&
            it.host.equals("llm-web.dewil.ru", true) && it.port == 18443 &&
            it.rawUserInfo == null && it.rawQuery == null && it.rawFragment == null &&
            it.rawPath == path
        }
    } catch (_: Exception) { false }
    fun validManifest(rawUrl: String): Boolean = exact(rawUrl, "/download/android/version.json")
    fun validApk(rawUrl: String, versionCode: Int): Boolean = versionCode > 0 &&
        exact(rawUrl, "/download/android/ai-control-$versionCode.apk")
}
