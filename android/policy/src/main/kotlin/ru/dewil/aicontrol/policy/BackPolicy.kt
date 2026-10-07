package ru.dewil.aicontrol.policy

enum class BackDecision { DISMISS_DIALOG, HIDE_IME, PANEL_BACK, LEAVE_ACTIVITY }

object BackPolicy {
    fun decide(imeVisible: Boolean, dialogVisible: Boolean, hasPanelHistory: Boolean): BackDecision = when {
        dialogVisible -> BackDecision.DISMISS_DIALOG
        imeVisible -> BackDecision.HIDE_IME
        hasPanelHistory -> BackDecision.PANEL_BACK
        else -> BackDecision.LEAVE_ACTIVITY
    }
}
