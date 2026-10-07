package ru.dewil.aicontrol.updater

import android.content.Context
import android.os.SystemClock
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withContext
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import ru.dewil.aicontrol.policy.UpdateUrlPolicy
import kotlin.coroutines.coroutineContext
import kotlin.coroutines.resume

class UpdateDownloader(private val context: Context) {

    suspend fun download(info: UpdateInfo, onProgress: (Int) -> Unit): DownloadResult {
        if (!UpdateUrlPolicy.validApk(info.apkUrl, info.versionCode)) {
            return DownloadResult.Failure(FailureReason.INVALID_URL)
        }
        return try {
            withTimeout(TOTAL_TIMEOUT_MS) {
                withContext(Dispatchers.IO) { cancellableDownload(info, onProgress) }
            }
        } catch (error: TimeoutCancellationException) {
            if (!currentCoroutineContext().isActive) throw error
            DownloadResult.Failure(FailureReason.NETWORK)
        }
    }

    private suspend fun cancellableDownload(
        info: UpdateInfo,
        onProgress: (Int) -> Unit,
    ): DownloadResult = suspendCancellableCoroutine { continuation ->
        val connection = AtomicReference<HttpURLConnection?>()
        val partFile = AtomicReference<File?>()
        val readyFile = AtomicReference<File?>()
        val job = CoroutineScope(continuation.context).launch(Dispatchers.IO) {
            val result = try {
                downloadBlocking(info, onProgress, connection, partFile, readyFile)
            } catch (_: CancellationException) {
                partFile.getAndSet(null)?.delete()
                readyFile.getAndSet(null)?.delete()
                return@launch
            } catch (_: Exception) {
                partFile.getAndSet(null)?.delete()
                readyFile.getAndSet(null)?.delete()
                DownloadResult.Failure(FailureReason.NETWORK)
            } finally {
                connection.getAndSet(null)?.disconnect()
            }
            continuation.resume(result) { _, undelivered, _ ->
                if (undelivered is DownloadResult.Success && readyFile.compareAndSet(undelivered.file, null)) {
                    undelivered.file.delete()
                }
            }
        }
        continuation.invokeOnCancellation {
            connection.getAndSet(null)?.disconnect()
            partFile.getAndSet(null)?.delete()
            readyFile.getAndSet(null)?.delete()
            job.cancel()
        }
    }

    private suspend fun downloadBlocking(
        info: UpdateInfo,
        onProgress: (Int) -> Unit,
        connectionRef: AtomicReference<HttpURLConnection?>,
        partRef: AtomicReference<File?>,
        readyRef: AtomicReference<File?>,
    ): DownloadResult {
        val part = File.createTempFile("ai-control-update-", ".part", context.cacheDir)
        partRef.set(part)
        var connection: HttpURLConnection? = null
        try {
            val deadline = SystemClock.elapsedRealtime() + TOTAL_TIMEOUT_MS
            connection = (URL(info.apkUrl).openConnection() as HttpURLConnection).apply {
                instanceFollowRedirects = false
                useCaches = false
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
            }
            connectionRef.set(connection)
            connection.connect()
            if (connection.responseCode !in 200..299) return DownloadResult.Failure(FailureReason.NETWORK)

            val expectedLength = connection.contentLengthLong
            if (expectedLength > MAX_APK_BYTES) return DownloadResult.Failure(FailureReason.TOO_LARGE)

            val digest = MessageDigest.getInstance("SHA-256")
            var downloaded = 0L
            connection.inputStream.use { input ->
                FileOutputStream(part).use { output ->
                    val buffer = ByteArray(BUFFER_SIZE)
                    while (true) {
                        coroutineContext.ensureActive()
                        if (SystemClock.elapsedRealtime() >= deadline) {
                            return DownloadResult.Failure(FailureReason.NETWORK)
                        }
                        val count = input.read(buffer)
                        if (count < 0) break
                        downloaded += count
                        if (downloaded > MAX_APK_BYTES || (expectedLength >= 0 && downloaded > expectedLength)) {
                            return DownloadResult.Failure(FailureReason.TOO_LARGE)
                        }
                        output.write(buffer, 0, count)
                        digest.update(buffer, 0, count)
                        if (expectedLength > 0) {
                            onProgress(((downloaded * 99) / expectedLength).toInt().coerceIn(0, 99))
                        }
                    }
                    output.fd.sync()
                }
            }
            if (downloaded == 0L || (expectedLength >= 0 && downloaded != expectedLength)) {
                return DownloadResult.Failure(FailureReason.INCOMPLETE)
            }
            if (SystemClock.elapsedRealtime() >= deadline) return DownloadResult.Failure(FailureReason.NETWORK)
            if (!Sha256.toHex(digest.digest()).equals(info.sha256, ignoreCase = true)) {
                return DownloadResult.Failure(FailureReason.CHECKSUM_MISMATCH)
            }

        val ready = File(context.cacheDir, "ai-control-update-${info.versionCode}-${UUID.randomUUID()}.apk")
            Files.move(part.toPath(), ready.toPath(), StandardCopyOption.ATOMIC_MOVE)
            readyRef.set(ready)
            coroutineContext.ensureActive()
            partRef.set(null)
            onProgress(100)
            return DownloadResult.Success(ready)
        } catch (error: IOException) {
            return DownloadResult.Failure(FailureReason.NETWORK)
        } finally {
            connection?.disconnect()
            connectionRef.compareAndSet(connection, null)
            if (partRef.compareAndSet(part, null)) part.delete()
        }
    }

    companion object {
        private const val CONNECT_TIMEOUT_MS = 15_000
        private const val READ_TIMEOUT_MS = 15_000
        private const val TOTAL_TIMEOUT_MS = 120_000L
        private const val MAX_APK_BYTES = 100L * 1024 * 1024
        private const val BUFFER_SIZE = 16 * 1024
    }
}
