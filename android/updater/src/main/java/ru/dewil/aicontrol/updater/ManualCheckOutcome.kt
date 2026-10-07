package ru.dewil.aicontrol.updater

enum class ManualCheckResult { UPDATE_AVAILABLE, UP_TO_DATE, CHECK_FAILED, BUSY }

/** Общие правила разбора и сравнения не дают ручной проверке расходиться с фоновой. */
object ManualCheckOutcome {
    fun of(busy: Boolean, fetched: String?, installedVersionCode: Int): ManualCheckResult {
        if (busy) return ManualCheckResult.BUSY
        val info = fetched?.let(UpdateInfoParser::parse) ?: return ManualCheckResult.CHECK_FAILED
        return if (UpdateDecision.shouldOffer(installedVersionCode, info)) {
            ManualCheckResult.UPDATE_AVAILABLE
        } else {
            ManualCheckResult.UP_TO_DATE
        }
    }
}
