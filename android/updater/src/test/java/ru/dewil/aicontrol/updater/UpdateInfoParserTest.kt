package ru.dewil.aicontrol.updater

// Regression cases adapted from the Gid updater at 0057b644; these are not blind tests.

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UpdateInfoParserTest {

    private val validHash = "a".repeat(64)

    private fun json(
        versionCode: String = "2",
        versionName: String = "\"0.2\"",
        apkUrl: String = "\"https://llm-web.dewil.ru:18443/download/android/ai-control-2.apk\"",
        sha256: String = "\"$validHash\"",
    ) = """
        {"versionCode": $versionCode, "versionName": $versionName, "apkUrl": $apkUrl, "sha256": $sha256}
    """.trimIndent()

    @Test
    fun `parses a well-formed version json`() {
        val info = UpdateInfoParser.parse(json())
        assertEquals(
            UpdateInfo(2, "0.2", "https://llm-web.dewil.ru:18443/download/android/ai-control-2.apk", validHash),
            info,
        )
    }

    @Test
    fun `missing field yields null`() {
        val json = """{"versionCode": 2, "versionName": "0.2", "apkUrl": "https://llm-web.dewil.ru:18443/download/android/ai-control-2.apk"}"""
        assertNull(UpdateInfoParser.parse(json))
    }

    @Test
    fun `non-https apkUrl is rejected`() {
        assertNull(UpdateInfoParser.parse(json(apkUrl = "\"http://llm-web.dewil.ru:18443/download/android/ai-control-2.apk\"")))
    }

    @Test
    fun `malformed sha256 is rejected`() {
        assertNull(UpdateInfoParser.parse(json(sha256 = "\"not-a-hash\"")))
    }

    @Test
    fun `non-numeric versionCode is rejected`() {
        val json = """{"versionCode": "two", "versionName": "0.2", "apkUrl": "https://llm-web.dewil.ru:18443/download/android/ai-control-2.apk", "sha256": "$validHash"}"""
        assertNull(UpdateInfoParser.parse(json))
    }

    @Test
    fun `garbage input yields null`() {
        assertNull(UpdateInfoParser.parse("not json at all"))
    }

    @Test
    fun `INV_UPD_02_truncated closing brace is rejected even though every field regex still matches`() {
        // Найдено сверкой 24.09.2026: без структурной проверки регулярки по отдельным
        // полям все еще находили значения в документе без финальной "}".
        val truncated = json().trimEnd().removeSuffix("}")
        assertNull(UpdateInfoParser.parse(truncated))
    }

    @Test
    fun `INV_UPD_02_fractional versionCode is rejected instead of silently truncated`() {
        assertNull(UpdateInfoParser.parse(json(versionCode = "7.5")))
    }

    @Test
    fun `INV_UPD_02_valid document with extra unknown field still parses`() {
        val withExtra = json().trimEnd().removeSuffix("}") + ""","releaseNotes":"текст"}"""
        val info = UpdateInfoParser.parse(withExtra)
        assertEquals(2, info?.versionCode)
    }

    @Test
    fun `INV_UPD_02_extra field whose string value contains a brace still parses`() {
        // Регрессия regex-подхода (вторая сверка 24.09.2026): подсчет "{"/"}" по всей строке
        // ломался на скобках внутри строковых значений. Настоящий JSON-парсер их не путает.
        val withBraceInString = json().trimEnd().removeSuffix("}") + ""","note":"{"}"""
        val info = UpdateInfoParser.parse(withBraceInString)
        assertEquals(2, info?.versionCode)
    }

    @Test
    fun `INV_UPD_02_fields nested in a sub-object are not found at top level`() {
        val nested = """{"data": ${json()}}"""
        assertNull(UpdateInfoParser.parse(nested))
    }

    @Test
    fun `INV_UPD_02_missing comma between fields is rejected`() {
        val noComma = """{"versionCode": 2 "versionName": "0.2", "apkUrl": "https://llm-web.dewil.ru:18443/download/android/ai-control-2.apk", "sha256": "$validHash"}"""
        assertNull(UpdateInfoParser.parse(noComma))
    }

    @Test
    fun `INV_UPD_02_trailing garbage after a valid object is rejected`() {
        // Найдено третьей сверкой 24.09.2026: платформенный org.json Android не требует
        // конца ввода после объекта и молча принимал документ с хвостом.
        assertNull(UpdateInfoParser.parse(json() + " garbage"))
    }

    @Test
    fun `INV_UPD_02_single quotes around keys and strings are rejected`() {
        val singleQuoted = """{'versionCode': 2, 'versionName': '0.2', 'apkUrl': 'https://llm-web.dewil.ru:18443/download/android/ai-control-2.apk', 'sha256': '$validHash'}"""
        assertNull(UpdateInfoParser.parse(singleQuoted))
    }

    @Test
    fun `INV_UPD_02_versionCode overflowing Int range is rejected instead of wrapping`() {
        // 4294967303 переполняет Int (обрезка Long.toInt() дала бы 7); Long.MAX_VALUE
        // тоже проверяет, что переполнение отсекается диапазоном, а не try-catch.
        assertNull(UpdateInfoParser.parse(json(versionCode = "4294967303")))
        assertNull(UpdateInfoParser.parse(json(versionCode = "2147483648"))) // Int.MAX_VALUE + 1
        assertNull(UpdateInfoParser.parse(json(versionCode = Long.MAX_VALUE.toString())))
    }

    private fun doc(versionCodeLiteral: String) =
        """{"versionCode": $versionCodeLiteral, "versionName": "0.6", "apkUrl": "https://llm-web.dewil.ru:18443/download/android/ai-control-$versionCodeLiteral.apk", "sha256": "${"a".repeat(64)}"}"""

    @Test
    fun INV_UPD_02_versionCode_invalidLiterals_rejected() {
        for (literal in listOf("abc", "1e3", "01", "-1", "1.0", "Infinity", "NaN", "true", "null", "9223372036854775808", "2147483648")) {
            assertNull("литерал $literal", UpdateInfoParser.parse(doc(literal)))
        }
    }

    @Test
    fun INV_UPD_02_versionCode_validLiterals_accepted() {
        assertNull(UpdateInfoParser.parse(doc("0")))
        assertEquals(1, UpdateInfoParser.parse(doc("1"))?.versionCode)
        assertEquals(6, UpdateInfoParser.parse(doc("6"))?.versionCode)
        assertEquals(Int.MAX_VALUE, UpdateInfoParser.parse(doc("2147483647"))?.versionCode)
    }

    @Test
    fun `duplicate keys are rejected even when values agree`() {
        val duplicate = doc("6").replace("\"versionCode\": 6", "\"versionCode\": 6, \"versionCode\": 6")
        assertNull(UpdateInfoParser.parse(duplicate))
    }

    @Test
    fun `version name is limited by Unicode code points`() {
        val allowed = doc("6").replace("0.6", "😀".repeat(64))
        val tooLong = doc("6").replace("0.6", "😀".repeat(65))
        assertEquals(6, UpdateInfoParser.parse(allowed)?.versionCode)
        assertNull(UpdateInfoParser.parse(tooLong))
    }
}
