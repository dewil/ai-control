package ru.dewil.aicontrol.updater

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Source-blind public parser probes: INV-AND-08, no updater implementation reads. */
class UpdateInfoParserStrictJsonProbeTest {
    private fun json(unknown: String? = null, name: String = "\"0.2\""): String {
        val extra = if (unknown == null) "" else ",\"unknown\":$unknown"
        return """{"versionCode":2,"versionName":$name,"apkUrl":"https://llm-web.dewil.ru:18443/download/android/ai-control-2.apk","sha256":"${"a".repeat(64)}"$extra}"""
    }

    private fun rejectUnknown(literal: String) {
        assertNull("Malformed unknown-field JSON must invalidate the whole manifest",
            UpdateInfoParser.parse(json(unknown = literal)))
    }

    @Test fun rejectsUnknownNaN() = rejectUnknown("NaN")
    @Test fun rejectsUnknownInfinity() = rejectUnknown("Infinity")
    @Test fun rejectsUnknownNegativeInfinity() = rejectUnknown("-Infinity")
    @Test fun rejectsUnknownBareToken() = rejectUnknown("arbitraryBareToken")
    @Test fun rejectsUnknownNumberLeadingZero() = rejectUnknown("01")
    @Test fun rejectsUnknownNumberIncompleteExponent() = rejectUnknown("1e")

    @Test fun rejectsEscapedUnpairedHighSurrogateInVersionName() {
        assertNull(UpdateInfoParser.parse(json(name = """"\uD800"""")))
    }

    @Test fun rejectsEscapedUnpairedLowSurrogateInVersionName() {
        assertNull(UpdateInfoParser.parse(json(name = """"\uDFFF"""")))
    }

    @Test fun rejectsEscapedUnpairedSurrogateInUnknownNestedString() {
        rejectUnknown("""{"nested":["\uD800"]}""")
    }

    @Test fun acceptsValidUnknownJsonValuesWithoutChangingRelease() {
        val expected = UpdateInfoParser.parse(json())
        assertEquals(2, expected?.versionCode)
        for (literal in listOf("""{"nested":[true,null,12.5,"text"]}""",
                """"quoted text"""", "null", "true", "false", "12.5", "-1.25e+2")) {
            assertEquals("Valid unknown JSON field must remain ignored", expected,
                UpdateInfoParser.parse(json(unknown = literal)))
        }
    }

    @Test fun acceptsProperlyPairedEscapedSurrogateInUnknownNestedString() {
        val expected = UpdateInfoParser.parse(json())
        assertEquals(2, expected?.versionCode)
        assertEquals(expected, UpdateInfoParser.parse(json(unknown = """{"nested":"\uD83D\uDE00"}""")))
    }
}
