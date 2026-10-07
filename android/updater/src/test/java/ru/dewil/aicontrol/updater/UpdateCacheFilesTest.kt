package ru.dewil.aicontrol.updater

import java.nio.file.Files
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateCacheFilesTest {
    @Test
    fun cleanupDeletesOnlyUpdaterPartialFiles() {
        val cache = Files.createTempDirectory("updater-cache-test").toFile()
        try {
            val interrupted = cache.resolve("ai-control-update-123.tmp.part")
            val ready = cache.resolve("ai-control-update-123-ready.apk")
            val unrelated = cache.resolve("other.part")
            val directory = cache.resolve("ai-control-update-nested.part")
            interrupted.writeText("partial")
            ready.writeText("verified")
            unrelated.writeText("keep")
            directory.mkdir()

            UpdateCacheFiles.cleanupPartialDownloads(cache)

            assertFalse(interrupted.exists())
            assertTrue(ready.exists())
            assertTrue(unrelated.exists())
            assertTrue(directory.isDirectory)
        } finally {
            cache.deleteRecursively()
        }
    }
}
