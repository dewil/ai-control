package ru.dewil.aicontrol.updater

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import ru.dewil.aicontrol.policy.UpdateUrlPolicy

/** Strict parser for the fixed, public Android update manifest. */
object UpdateInfoParser {
    private const val MAX_MANIFEST_BYTES = 16 * 1024
    private val versionCodePattern = Regex("[1-9][0-9]{0,9}")
    private val sha256Pattern = Regex("[0-9a-fA-F]{64}")

    fun parse(json: String): UpdateInfo? {
        if (json.toByteArray(Charsets.UTF_8).size > MAX_MANIFEST_BYTES) return null
        val root = try {
            Json.parseToJsonElement(json) as? JsonObject ?: return null
        } catch (_: SerializationException) {
            return null
        } catch (_: IllegalArgumentException) {
            return null
        } catch (_: StackOverflowError) {
            return null
        }
        if (containsDuplicateKeys(json)) return null

        val versionCodeText = (root["versionCode"] as? JsonPrimitive)
            ?.takeIf { !it.isString }
            ?.content
            ?.takeIf(versionCodePattern::matches)
            ?: return null
        val versionCode = versionCodeText.toIntOrNull()?.takeIf { it > 0 } ?: return null
        val versionName = root.string("versionName")
            ?.takeIf { it.isNotBlank() && it.codePointCount(0, it.length) <= 64 }
            ?: return null
        val apkUrl = root.string("apkUrl")
            ?.takeIf { UpdateUrlPolicy.validApk(it, versionCode) }
            ?: return null
        val sha256 = root.string("sha256")
            ?.takeIf(sha256Pattern::matches)
            ?: return null

        return UpdateInfo(versionCode, versionName, apkUrl, sha256)
    }

    private fun JsonObject.string(name: String): String? {
        val primitive = this[name] as? JsonPrimitive ?: return null
        return primitive.content.takeIf { primitive.isString }
    }

    /** JsonObject keeps only one value for a repeated key, so scan keys before accepting it. */
    private fun containsDuplicateKeys(source: String): Boolean = try {
        DuplicateKeyScanner(source).hasDuplicates()
    } catch (_: Exception) {
        true
    }

    private class DuplicateKeyScanner(private val source: String) {
        private var index = 0
        private val jsonNumberPattern = Regex("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")

        fun hasDuplicates(): Boolean {
            skipWhitespace()
            readValue()
            skipWhitespace()
            return index != source.length
        }

        private fun readValue(depth: Int = 0) {
            require(depth <= MAX_NESTING_DEPTH)
            skipWhitespace()
            when (source.getOrNull(index)) {
                '{' -> readObject(depth + 1)
                '[' -> readArray(depth + 1)
                '"' -> decodeString(readStringToken())
                else -> readPrimitive()
            }
        }

        private fun readObject(depth: Int) {
            index++ // {
            skipWhitespace()
            if (source.getOrNull(index) == '}') {
                index++
                return
            }
            val keys = HashSet<String>()
            while (true) {
                skipWhitespace()
                val key = decodeString(readStringToken())
                if (!keys.add(key)) throw IllegalArgumentException("duplicate key")
                skipWhitespace()
                require(source.getOrNull(index) == ':')
                index++
                readValue(depth)
                skipWhitespace()
                when (source.getOrNull(index)) {
                    ',' -> index++
                    '}' -> { index++; return }
                    else -> throw IllegalArgumentException("invalid object")
                }
            }
        }

        private fun readArray(depth: Int) {
            index++ // [
            skipWhitespace()
            if (source.getOrNull(index) == ']') {
                index++
                return
            }
            while (true) {
                readValue(depth)
                skipWhitespace()
                when (source.getOrNull(index)) {
                    ',' -> index++
                    ']' -> { index++; return }
                    else -> throw IllegalArgumentException("invalid array")
                }
            }
        }

        private fun readStringToken(): String {
            val start = index
            require(source.getOrNull(index) == '"')
            index++
            while (index < source.length) {
                when (source[index++]) {
                    '\\' -> index++
                    '"' -> return source.substring(start, index)
                }
            }
            throw IllegalArgumentException("invalid string")
        }

        private fun decodeString(token: String): String {
            val decoded = (Json.parseToJsonElement(token) as? JsonPrimitive)
                ?.takeIf { it.isString }
                ?.content
                ?: throw IllegalArgumentException("invalid string")
            var position = 0
            while (position < decoded.length) {
                when {
                    Character.isHighSurrogate(decoded[position]) -> {
                        require(position + 1 < decoded.length && Character.isLowSurrogate(decoded[position + 1]))
                        position += 2
                    }
                    Character.isLowSurrogate(decoded[position]) -> throw IllegalArgumentException("invalid Unicode scalar")
                    else -> position++
                }
            }
            return decoded
        }

        private fun readPrimitive() {
            val start = index
            while (index < source.length && source[index] !in ",]} \t\r\n") index++
            require(index > start)
            val token = source.substring(start, index)
            require(token == "true" || token == "false" || token == "null" || jsonNumberPattern.matches(token))
        }

        private fun skipWhitespace() {
            while (source.getOrNull(index) in listOf(' ', '\t', '\r', '\n')) index++
        }

        companion object {
            private const val MAX_NESTING_DEPTH = 128
        }
    }
}
