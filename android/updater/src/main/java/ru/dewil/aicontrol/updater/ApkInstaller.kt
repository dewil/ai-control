package ru.dewil.aicontrol.updater

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.os.Build
import android.os.SystemClock
import java.io.File
import java.io.IOException
import java.security.DigestOutputStream
import java.security.MessageDigest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

enum class InstallOutcome { STARTED, FAILED, CHECKSUM_MISMATCH, INVALID_PACKAGE }

class ApkInstaller(private val context: Context) {

    suspend fun install(
        apkFile: File,
        info: UpdateInfo,
        attemptId: String,
        onCommitted: (sessionId: Int, attemptId: String, waitStartedAtMs: Long) -> Unit,
    ): InstallOutcome = withContext(Dispatchers.IO) {
        if (!matchesInstalledPackage(apkFile, info.versionCode)) return@withContext InstallOutcome.INVALID_PACKAGE

        var session: PackageInstaller.Session? = null
        var createdSessionId: Int? = null
        var committed = false
        try {
            val packageInstaller = context.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            params.setAppPackageName(context.packageName)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
            }
            val sessionId = packageInstaller.createSession(params)
            createdSessionId = sessionId
            val openedSession = packageInstaller.openSession(sessionId)
            session = openedSession

            val digest = MessageDigest.getInstance("SHA-256")
            apkFile.inputStream().use { input ->
                val output = openedSession.openWrite(SESSION_STREAM_NAME, 0, apkFile.length())
                try {
                    val digestingOutput = DigestOutputStream(output, digest)
                    input.copyTo(digestingOutput)
                    digestingOutput.flush()
                    openedSession.fsync(output)
                } finally {
                    output.close()
                }
            }
            if (!Sha256.toHex(digest.digest()).equals(info.sha256, ignoreCase = true)) {
                return@withContext InstallOutcome.CHECKSUM_MISMATCH
            }

            val resultIntent = Intent(context, InstallResultReceiver::class.java)
                .setPackage(context.packageName)
                .setAction("${context.packageName}.UPDATE_INSTALL_RESULT.$attemptId")
                .setData(android.net.Uri.parse("aicontrol-update://install-result/$attemptId"))
                .putExtra(InstallResultReceiver.EXTRA_ATTEMPT_ID, attemptId)
            val pendingIntent = PendingIntent.getBroadcast(
                context,
                sessionId,
                resultIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
            )
            withContext(Dispatchers.Main.immediate) {
                val waitStartedAtMs = SystemClock.elapsedRealtime()
                openedSession.commit(pendingIntent.intentSender)
                committed = true
                onCommitted(sessionId, attemptId, waitStartedAtMs)
            }
            InstallOutcome.STARTED
        } catch (error: CancellationException) {
            throw error
        } catch (error: IOException) {
            InstallOutcome.FAILED
        } catch (error: SecurityException) {
            InstallOutcome.FAILED
        } catch (error: RuntimeException) {
            InstallOutcome.FAILED
        } finally {
            if (!committed) {
                try {
                    session?.abandon()
                        ?: createdSessionId?.let { context.packageManager.packageInstaller.abandonSession(it) }
                } catch (_: Exception) {
                    // The platform may already have removed the incomplete session.
                }
            }
            session?.close()
        }
    }

    private fun matchesInstalledPackage(apkFile: File, expectedVersionCode: Int): Boolean {
        if (!apkFile.isFile) return false
        val packageManager = context.packageManager
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            PackageManager.GET_SIGNING_CERTIFICATES
        } else {
            @Suppress("DEPRECATION")
            PackageManager.GET_SIGNATURES
        }
        return try {
            val archived = packageManager.getPackageArchiveInfo(apkFile.absolutePath, flags) ?: return false
            if (archived.packageName != context.packageName ||
                longVersionCode(archived) != expectedVersionCode.toLong()) return false
            val archivedMinSdk = archived.applicationInfo?.minSdkVersion ?: return false
            val installed = packageManager.getPackageInfo(context.packageName, flags)
            val installedMinSdk = installed.applicationInfo?.minSdkVersion ?: return false
            if (archivedMinSdk < installedMinSdk || archivedMinSdk > Build.VERSION.SDK_INT) return false
            signerDigests(archived) == signerDigests(installed) && signerDigests(archived).isNotEmpty()
        } catch (_: Exception) {
            false
        }
    }

    @Suppress("DEPRECATION")
    private fun longVersionCode(info: PackageInfo): Long =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.longVersionCode else info.versionCode.toLong()

    private fun signerDigests(info: PackageInfo): Set<String> {
        val signatures: Array<Signature>? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            info.signingInfo?.apkContentsSigners
        } else {
            @Suppress("DEPRECATION")
            info.signatures
        }
        if (signatures.isNullOrEmpty()) return emptySet()
        return signatures.mapTo(linkedSetOf()) { signature ->
            Sha256.toHex(MessageDigest.getInstance("SHA-256").digest(signature.toByteArray()))
        }
    }

    companion object {
        private const val SESSION_STREAM_NAME = "ai-control-update"
    }
}
