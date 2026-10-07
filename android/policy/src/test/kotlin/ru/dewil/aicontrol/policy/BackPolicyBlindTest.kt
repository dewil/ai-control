package ru.dewil.aicontrol.policy

import org.junit.Assert.assertEquals
import org.junit.Test

class BackPolicyBlindTest {
    @Test fun INV_AND_03DialogHasPriorityOverImeHistoryAndLeave() {
        assertEquals(BackDecision.DISMISS_DIALOG, BackPolicy.decide(imeVisible = true, dialogVisible = true, hasPanelHistory = true))
        assertEquals(BackDecision.DISMISS_DIALOG, BackPolicy.decide(imeVisible = false, dialogVisible = true, hasPanelHistory = false))
    }

    @Test fun INV_AND_03ImeIsHiddenBeforePanelHistoryOrLeave() {
        assertEquals(BackDecision.HIDE_IME, BackPolicy.decide(imeVisible = true, dialogVisible = false, hasPanelHistory = true))
        assertEquals(BackDecision.HIDE_IME, BackPolicy.decide(imeVisible = true, dialogVisible = false, hasPanelHistory = false))
    }

    @Test fun INV_AND_03PanelHistoryPrecedesLeavingActivity() {
        assertEquals(BackDecision.PANEL_BACK, BackPolicy.decide(imeVisible = false, dialogVisible = false, hasPanelHistory = true))
    }

    @Test fun INV_AND_03NoDialogImeOrHistoryLeavesActivity() {
        assertEquals(BackDecision.LEAVE_ACTIVITY, BackPolicy.decide(imeVisible = false, dialogVisible = false, hasPanelHistory = false))
    }
}
