package ru.dewil.aicontrol.updater

import java.io.File

sealed class DownloadResult {
    data class Success(val file: File) : DownloadResult()
    data class Failure(val reason: FailureReason) : DownloadResult()
}

enum class FailureReason { NETWORK, CHECKSUM_MISMATCH, INVALID_URL, TOO_LARGE, INCOMPLETE }
