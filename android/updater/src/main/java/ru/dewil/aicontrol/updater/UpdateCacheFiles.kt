package ru.dewil.aicontrol.updater

import java.io.File

/** Removes only interrupted downloads created by this updater. */
internal object UpdateCacheFiles {
    private const val PART_PREFIX = "ai-control-update-"

    fun cleanupPartialDownloads(cacheDir: File) {
        cacheDir.listFiles()?.forEach { file ->
            if (file.name.startsWith(PART_PREFIX) && file.name.endsWith(".part") && file.isFile) {
                file.delete()
            }
        }
    }
}
