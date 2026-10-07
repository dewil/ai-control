package ru.dewil.aicontrol.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateUrlPolicyTest {
    private val origin = "https://llm-web.dewil.ru:18443"

    // INV-AND-08: the public feed has one fixed endpoint.
    @Test fun INV_AND_08CanonicalManifestUrlIsAllowed() {
        assertTrue(UpdateUrlPolicy.validManifest("$origin/download/android/version.json"))
    }

    // INV-AND-08: DNS host matching is case insensitive, with no suffix matching.
    @Test fun INV_AND_08UppercaseHostStillIdentifiesThePanel() {
        assertTrue(UpdateUrlPolicy.validManifest("https://LLM-WEB.DEWIL.RU:18443/download/android/version.json"))
    }

    // INV-AND-08: a manifest cannot be fetched from a different authority.
    @Test fun INV_AND_08ManifestRejectsOtherAuthoritiesAndSchemes() {
        for (url in listOf(
            "http://llm-web.dewil.ru:18443/download/android/version.json",
            "https://llm-web.dewil.ru/download/android/version.json",
            "https://llm-web.dewil.ru:443/download/android/version.json",
            "https://llm-web.dewil.ru:18444/download/android/version.json",
            "https://llm-web.dewil.ru.evil.test:18443/download/android/version.json",
            "https://user@llm-web.dewil.ru:18443/download/android/version.json"
        )) assertFalse(url, UpdateUrlPolicy.validManifest(url))
    }

    // INV-AND-08: byte-different paths and URL parameters are not the feed.
    @Test fun INV_AND_08ManifestRejectsAlternatePathsQueryAndFragment() {
        for (url in listOf(
            "$origin/download/android/",
            "$origin/download/android/version.json/",
            "$origin/download/android/Version.json",
            "$origin/download/android/version.json?next=1",
            "$origin/download/android/version.json#latest",
            "$origin/download/android/../android/version.json",
            "$origin/download/android/%2e%2e/version.json",
            "$origin/download%2Fandroid/version.json",
            "$origin/download/android/%76ersion.json"
        )) assertFalse(url, UpdateUrlPolicy.validManifest(url))
    }

    // INV-AND-09: the APK filename must match the selected positive code.
    @Test fun INV_AND_09CanonicalApkUrlForFirstVersionIsAllowed() {
        assertTrue(UpdateUrlPolicy.validApk("$origin/download/android/ai-control-1.apk", 1))
    }

    // INV-AND-09: the upper bound remains a valid Android version code.
    @Test fun INV_AND_09MaximumPositiveVersionCodeIsAllowed() {
        assertTrue(UpdateUrlPolicy.validApk("$origin/download/android/ai-control-2147483647.apk", Int.MAX_VALUE))
    }

    // INV-AND-09: DNS host case does not change the selected APK's identity.
    @Test fun INV_AND_09UppercaseHostIsAllowedForTheSameApk() {
        assertTrue(UpdateUrlPolicy.validApk("https://LLM-WEB.DEWIL.RU:18443/download/android/ai-control-17.apk", 17))
    }

    // INV-AND-09: no zero, negative, mismatched, or padded version aliases.
    @Test fun INV_AND_09ApkVersionMustBePositiveAndExact() {
        assertFalse(UpdateUrlPolicy.validApk("$origin/download/android/ai-control-0.apk", 0))
        assertFalse(UpdateUrlPolicy.validApk("$origin/download/android/ai-control--1.apk", -1))
        assertFalse(UpdateUrlPolicy.validApk("$origin/download/android/ai-control-2.apk", 1))
        assertFalse(UpdateUrlPolicy.validApk("$origin/download/android/ai-control-01.apk", 1))
    }

    // INV-AND-09: the APK URL has the same strict transport and authority rules.
    @Test fun INV_AND_09ApkRejectsOtherOriginsAndUrlParameters() {
        for (url in listOf(
            "http://llm-web.dewil.ru:18443/download/android/ai-control-17.apk",
            "https://llm-web.dewil.ru/download/android/ai-control-17.apk",
            "https://llm-web.dewil.ru:18444/download/android/ai-control-17.apk",
            "https://llm-web.dewil.ru.evil.test:18443/download/android/ai-control-17.apk",
            "https://user@llm-web.dewil.ru:18443/download/android/ai-control-17.apk",
            "$origin/download/android/ai-control-17.apk?download=1",
            "$origin/download/android/ai-control-17.apk#file"
        )) assertFalse(url, UpdateUrlPolicy.validApk(url, 17))
    }

    // INV-AND-09: normalization and percent decoding cannot create path aliases.
    @Test fun INV_AND_09ApkRejectsEncodedAndTraversalPaths() {
        for (url in listOf(
            "$origin/download/android/../android/ai-control-17.apk",
            "$origin/download/android/%2e%2e/ai-control-17.apk",
            "$origin/download%2Fandroid/ai-control-17.apk",
            "$origin/download/android/%61i-control-17.apk",
            "$origin/download/android/ai-control-17.apk/"
        )) assertFalse(url, UpdateUrlPolicy.validApk(url, 17))
    }
}
