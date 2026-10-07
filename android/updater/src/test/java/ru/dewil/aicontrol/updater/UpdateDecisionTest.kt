package ru.dewil.aicontrol.updater

// Regression cases adapted from the Gid updater at 0057b644; these are not blind tests.

import org.junit.Assert.assertEquals
import org.junit.Test

class UpdateDecisionTest {

    private fun remote(versionCode: Int) = UpdateInfo(
        versionCode,
        "x",
        "https://llm-web.dewil.ru:18443/download/android/ai-control-$versionCode.apk",
        "a".repeat(64),
    )

    @Test
    fun `newer remote version offers update`() {
        assertEquals(true, UpdateDecision.shouldOffer(installedVersionCode = 2, remote = remote(3)))
    }

    @Test
    fun `same version does not offer update`() {
        assertEquals(false, UpdateDecision.shouldOffer(installedVersionCode = 2, remote = remote(2)))
    }

    @Test
    fun `older remote version does not offer update`() {
        assertEquals(false, UpdateDecision.shouldOffer(installedVersionCode = 2, remote = remote(1)))
    }
}
