package ru.dewil.aicontrol.updater

/** Public update-feed metadata; the APK URL is revalidated before every download. */
data class UpdateInfo(
    val versionCode: Int,
    val versionName: String,
    val apkUrl: String,
    val sha256: String,
)
