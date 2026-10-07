package ru.dewil.aicontrol.updater

import java.security.MessageDigest

/**
 * Чистая Kotlin-логика проверки контрольной суммы. `MessageDigest` - часть
 * стандартной JDK, доступна и в юнит-тестах без Android-зависимостей.
 */
object Sha256 {

    fun toHex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

    fun hex(bytes: ByteArray): String = toHex(MessageDigest.getInstance("SHA-256").digest(bytes))

    fun matches(bytes: ByteArray, expectedHex: String): Boolean =
        hex(bytes).equals(expectedHex.trim(), ignoreCase = true)
}
