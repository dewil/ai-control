package ru.dewil.aicontrol.policy

import org.junit.Assert.assertEquals
import org.junit.Test

class OriginPolicyBlindTest {
    private fun classify(
        url: String,
        main: Boolean = true,
        gesture: Boolean = false,
        method: String = "GET",
        redirect: Boolean = false,
    ) = OriginPolicy.classify(url, main, gesture, method, redirect)

    @Test fun INV_AND_03_exactPanelOriginAllowsMainFrameGetAndPost() {
        assertEquals(NavigationDecision.ALLOW_PANEL, classify("https://llm-web.dewil.ru:18443/"))
        assertEquals(NavigationDecision.ALLOW_PANEL, classify("https://llm-web.dewil.ru:18443/api/send", method = "POST"))
    }

    @Test fun INV_AND_03_sameOriginUsesEffectivePortAndAsciiHostExactly() {
        assertEquals(NavigationDecision.BLOCK, classify("https://llm-web.dewil.ru/"))
        assertEquals(NavigationDecision.BLOCK, classify("https://llm-web.dewil.ru:443/"))
        assertEquals(NavigationDecision.BLOCK, classify("https://llm-web.dewil.ru:18444/"))
        assertEquals(NavigationDecision.BLOCK, classify("https://sub.llm-web.dewil.ru:18443/"))
        assertEquals(NavigationDecision.BLOCK, classify("https://llm-web.dewil.ru.evil.test:18443/"))
    }

    @Test fun INV_AND_03_userinfoAndNonHttpsOrCustomSchemesAreBlocked() {
        listOf(
            "https://user@llm-web.dewil.ru:18443/",
            "http://llm-web.dewil.ru:18443/",
            "file:///tmp/a", "content://authority/a", "data:text/html,x",
            "javascript:alert(1)", "intent://host/#Intent;scheme=https;end", "custom://host/path",
            "https://llm-web.dewil.ru:18443/%zz",
        ).forEach { assertEquals(it, NavigationDecision.BLOCK, classify(it)) }
    }

    @Test fun INV_AND_03_externalOnlyOpensForMainFrameGestureGetWithoutRedirect() {
        val external = "https://example.org/path"
        assertEquals(NavigationDecision.OPEN_BROWSER, classify(external, gesture = true))
        assertEquals(NavigationDecision.OPEN_BROWSER, classify("http://example.org/", gesture = true))
        assertEquals(NavigationDecision.BLOCK, classify(external, main = false, gesture = true))
        assertEquals(NavigationDecision.BLOCK, classify(external, gesture = false))
        assertEquals(NavigationDecision.BLOCK, classify(external, gesture = true, method = "POST"))
        assertEquals(NavigationDecision.BLOCK, classify(external, gesture = true, redirect = true))
    }

    @Test fun INV_AND_03_sameOriginSubframeIsAllowedButExternalSubframeIsBlocked() {
        assertEquals(NavigationDecision.ALLOW_PANEL, classify("https://llm-web.dewil.ru:18443/frame", main = false))
        assertEquals(NavigationDecision.BLOCK, classify("https://example.org/frame", main = false, gesture = true))
    }

    @Test fun INV_AND_12_exactDownloadLandingOpensOnlyOnExplicitMainFrameGet() {
        val landing = "https://llm-web.dewil.ru:18443/download/android/"
        assertEquals(NavigationDecision.OPEN_BROWSER, classify(landing, gesture = true))
        assertEquals(NavigationDecision.BLOCK, classify(landing, gesture = false))
        assertEquals(NavigationDecision.BLOCK, classify(landing, main = false, gesture = true))
        assertEquals(NavigationDecision.BLOCK, classify(landing, gesture = true, method = "POST"))
        assertEquals(NavigationDecision.BLOCK, classify(landing, gesture = true, redirect = true))
    }

    @Test fun INV_AND_12DownloadLandingQueryFragmentAndLookalikePathsAreBlocked() {
        listOf(
            "https://llm-web.dewil.ru:18443/download/android/?x=1",
            "https://llm-web.dewil.ru:18443/download/android/#x",
            "https://llm-web.dewil.ru:18443/download/android",
            "https://llm-web.dewil.ru:18443/download/android/extra",
        ).forEach { assertEquals(it, NavigationDecision.BLOCK, classify(it, gesture = true)) }
    }

    @Test fun INV_AND_03UnknownMethodsAreBlocked() {
        listOf("PUT", "DELETE", "OPTIONS", "get", "", "PATCH").forEach {
            assertEquals(it, NavigationDecision.BLOCK, classify("https://llm-web.dewil.ru:18443/", method = it))
        }
    }
}
