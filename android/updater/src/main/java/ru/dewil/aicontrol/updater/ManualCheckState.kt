package ru.dewil.aicontrol.updater

/** Идентификатор нужен, чтобы подтверждение старого сообщения не стерло новый результат. */
data class ManualCheckState(
    val checking: Boolean = false,
    val pendingResult: ManualCheckResult? = null,
    val resultId: Long = 0L,
)
