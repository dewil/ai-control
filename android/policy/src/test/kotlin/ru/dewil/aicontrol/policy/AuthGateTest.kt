package ru.dewil.aicontrol.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthGateTest {
    // INV-AUTHAND-03: only the current foreground admission may affect the page.
    @Test fun INV_AUTHAND_03StopInvalidatesAnInFlightAdmission() {
        val gate = AuthGate()
        val first = gate.begin()
        assertTrue(gate.canApply(first))

        gate.stop()
        assertFalse(gate.canApply(first))

        val second = gate.begin()
        assertTrue(second > first)
        assertTrue(gate.canApply(second))
        assertFalse(gate.canApply(first))
    }

    // INV-AUTHAND-05: an old response must not reopen a page after logout.
    @Test fun INV_AUTHAND_05LogoutBlocksLateAndNewAdmissions() {
        val gate = AuthGate()
        val inFlight = gate.begin()
        gate.logout()
        assertFalse(gate.canApply(inFlight))

        val afterLogout = gate.begin()
        assertTrue(afterLogout > inFlight)
        assertFalse(gate.canApply(afterLogout))

        val afterLogin = gate.resetAfterExplicitLogin()
        assertTrue(afterLogin > afterLogout)
        assertTrue(gate.canApply(afterLogin))
        assertFalse(gate.canApply(inFlight))
        assertFalse(gate.canApply(afterLogout))
    }

    // INV-AUTHAND-03/05: revoked admission remains terminal until explicit login.
    @Test fun INV_AUTHAND_05DenialCannotBeClearedByForegroundOpen() {
        val gate = AuthGate()
        val inFlight = gate.begin()
        gate.deny()
        assertFalse(gate.canApply(inFlight))

        val afterDenial = gate.begin()
        assertTrue(afterDenial > inFlight)
        assertFalse(gate.canApply(afterDenial))

        val afterLogin = gate.resetAfterExplicitLogin()
        assertTrue(afterLogin > afterDenial)
        assertTrue(gate.canApply(afterLogin))
        assertFalse(gate.canApply(afterDenial))
    }

    // INV-AUTHAND-04/05: each new foreground generation supersedes earlier work.
    @Test fun INV_AUTHAND_04OnlyLatestForegroundGenerationCanApply() {
        val gate = AuthGate()
        val first = gate.begin()
        val second = gate.begin()

        assertTrue(second > first)
        assertFalse(gate.canApply(first))
        assertTrue(gate.canApply(second))
        assertFalse(gate.canApply(second + 1))
    }

    // INV-AUTHAND-06: state from one gate cannot authorize another instance.
    @Test fun INV_AUTHAND_06IndependentGatesKeepIndependentTerminalState() {
        val denied = AuthGate()
        val active = AuthGate()
        val deniedGeneration = denied.begin()
        val activeGeneration = active.begin()

        denied.deny()
        assertFalse(denied.canApply(deniedGeneration))
        assertTrue(active.canApply(activeGeneration))
    }
}
