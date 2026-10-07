package ru.dewil.aicontrol.policy

object AuthOutcome {
    fun shouldClearToken(status: Int, error: String?): Boolean =
        status == 401 && error == "device_unauthorized"
}
