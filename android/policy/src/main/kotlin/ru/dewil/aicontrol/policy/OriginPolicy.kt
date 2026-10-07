package ru.dewil.aicontrol.policy

import java.net.URI
import java.net.URISyntaxException
import java.util.Locale

enum class NavigationDecision { ALLOW_PANEL, OPEN_BROWSER, BLOCK }

object OriginPolicy {
    private const val PANEL_SCHEME = "https"
    private const val PANEL_HOST = "llm-web.dewil.ru"
    private const val PANEL_PORT = 18443
    private const val DOWNLOAD_PATH = "/download/android/"

    fun classify(
        rawUrl: String,
        mainFrame: Boolean,
        userGesture: Boolean,
        method: String,
        isRedirect: Boolean,
    ): NavigationDecision {
        if (rawUrl.isEmpty() || rawUrl.any { it.isISOControl() }) return NavigationDecision.BLOCK

        val uri = try {
            URI(rawUrl)
        } catch (error: URISyntaxException) {
            return NavigationDecision.BLOCK
        } catch (error: IllegalArgumentException) {
            return NavigationDecision.BLOCK
        }

        if (!uri.isAbsolute || uri.isOpaque || uri.rawUserInfo != null) return NavigationDecision.BLOCK

        val scheme = uri.scheme?.lowercase(Locale.ROOT) ?: return NavigationDecision.BLOCK
        if (scheme != "http" && scheme != "https") return NavigationDecision.BLOCK

        val host = uri.host ?: return NavigationDecision.BLOCK
        if (host.any { it.code > 0x7f }) return NavigationDecision.BLOCK

        val port = uri.port
        if (port != -1 && port !in 1..65535) return NavigationDecision.BLOCK

        val isPanelOrigin = scheme == PANEL_SCHEME &&
            host.equals(PANEL_HOST, ignoreCase = true) && port == PANEL_PORT

        if (isPanelOrigin) {
            if (uri.rawPath == "/download/android" || uri.rawPath?.startsWith(DOWNLOAD_PATH) == true) {
                if (uri.rawPath != DOWNLOAD_PATH) return NavigationDecision.BLOCK
            }
            if (uri.rawPath == DOWNLOAD_PATH) {
                if (uri.rawQuery != null || uri.rawFragment != null) return NavigationDecision.BLOCK
                return if (mainFrame && userGesture && method == "GET" && !isRedirect) {
                    NavigationDecision.OPEN_BROWSER
                } else {
                    NavigationDecision.BLOCK
                }
            }

            return if (method == "GET" || method == "POST") {
                NavigationDecision.ALLOW_PANEL
            } else {
                NavigationDecision.BLOCK
            }
        }

        return if (mainFrame && userGesture && method == "GET" && !isRedirect) {
            NavigationDecision.OPEN_BROWSER
        } else {
            NavigationDecision.BLOCK
        }
    }
}
