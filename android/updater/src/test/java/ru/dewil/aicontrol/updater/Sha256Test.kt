package ru.dewil.aicontrol.updater

// Regression cases adapted from the Gid updater at 0057b644; these are not blind tests.

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Sha256Test {

    @Test
    fun `hex of empty byte array is the known sha256 of empty input`() {
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            Sha256.hex(ByteArray(0)),
        )
    }

    @Test
    fun `matches is case-insensitive`() {
        val hex = Sha256.hex("mobile-music".toByteArray())
        assertTrue(Sha256.matches("mobile-music".toByteArray(), hex.uppercase()))
    }

    @Test
    fun `matches trims whitespace around expected hash`() {
        val hex = Sha256.hex("mobile-music".toByteArray())
        assertTrue(Sha256.matches("mobile-music".toByteArray(), "  $hex  "))
    }

    @Test
    fun `wrong hash does not match`() {
        assertFalse(Sha256.matches("mobile-music".toByteArray(), "a".repeat(64)))
    }
}
