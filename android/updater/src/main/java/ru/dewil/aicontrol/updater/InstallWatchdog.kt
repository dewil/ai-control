package ru.dewil.aicontrol.updater

/** Монотонное ожидание ограничено, чтобы потерянный ответ системы не блокировал обновления. */
object InstallWatchdog {
    const val TIMEOUT_MS: Long = 90_000

    fun isStuck(waitStartedAtMs: Long, nowMs: Long, resultReceived: Boolean): Boolean =
        !resultReceived && nowMs >= waitStartedAtMs && nowMs - waitStartedAtMs >= TIMEOUT_MS
}
