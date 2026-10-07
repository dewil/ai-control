package ru.dewil.aicontrol.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthOutcomeTest {
    // INV-AUTHAND-03: only an explicit device admission denial clears the token.
    @Test fun INV_AUTHAND_03ExactDeviceUnauthorizedClearsToken() {
        assertTrue(AuthOutcome.shouldClearToken(401, "device_unauthorized"))
    }

    // INV-AUTHAND-04/06: transient and policy errors preserve recoverable admission.
    @Test fun INV_AUTHAND_06OriginStorageNetworkAndMalformedResponsesRetainToken() {
        assertFalse(AuthOutcome.shouldClearToken(403, "forbidden"))
        assertFalse(AuthOutcome.shouldClearToken(422, "invalid_request"))
        assertFalse(AuthOutcome.shouldClearToken(503, "unavailable"))
        assertFalse(AuthOutcome.shouldClearToken(0, null))
        assertFalse(AuthOutcome.shouldClearToken(200, null))
    }

    // INV-AUTHAND-05: a 401 alone is not proof that the device grant was revoked.
    @Test fun INV_AUTHAND_05OnlyExactSafeErrorCodeAuthorizesClearing() {
        assertFalse(AuthOutcome.shouldClearToken(401, null))
        assertFalse(AuthOutcome.shouldClearToken(401, ""))
        assertFalse(AuthOutcome.shouldClearToken(401, "unauthorized"))
        assertFalse(AuthOutcome.shouldClearToken(401, "device_unauthorized "))
        assertFalse(AuthOutcome.shouldClearToken(401, "Device_Unauthorized"))
        assertFalse(AuthOutcome.shouldClearToken(403, "device_unauthorized"))
    }

    // INV-AUTHAND-05: response classification is independent of prior outcomes.
    @Test fun INV_AUTHAND_05LaterRetryRemainsRecoverableAfterASeparateDenial() {
        assertTrue(AuthOutcome.shouldClearToken(401, "device_unauthorized"))
        assertFalse(AuthOutcome.shouldClearToken(503, "unavailable"))
        assertFalse(AuthOutcome.shouldClearToken(401, "forbidden"))
    }
}
