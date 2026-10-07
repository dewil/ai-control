package ru.dewil.aicontrol.updater

import android.content.Context
import android.content.Intent
import android.app.Activity
import android.app.Application
import android.os.Bundle
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import ru.dewil.aicontrol.policy.UpdateUrlPolicy
import ru.dewil.aicontrol.updater.R
import kotlin.coroutines.resume
import kotlin.coroutines.coroutineContext

enum class InstallReconciliation { NONE, INSTALLED, SESSION_ACTIVE, NOT_INSTALLED, UNKNOWN }

/** Application-owned updater state; no web cookie or authentication token enters this module. */
class UpdateRepository(
    private val context: Context,
    private val installedVersionCode: Int,
) {
    private val preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val downloader = UpdateDownloader(context)
    private val installer = ApkInstaller(context)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private var readyApk: java.io.File? = null
    private var installSessionId: Int? = preferences.getInt(KEY_INSTALL_SESSION, NO_SESSION).takeIf { it >= 0 }
    private var installAttemptId: String? = preferences.getString(KEY_INSTALL_ATTEMPT, null)
    private var installTargetVersion: Int? = preferences.getInt(KEY_INSTALL_TARGET, 0).takeIf { it > 0 }
    private var installWaitStartedAtMs: Long? = null
    private var installWatchdogJob: Job? = null
    @Volatile private var pendingConfirmation: Intent? = null
    @Volatile private var appForeground = false

    private val _state = MutableStateFlow(restoreState())
    val state: StateFlow<UpdateUiState> = _state.asStateFlow()
    private val _manualCheckState = MutableStateFlow(ManualCheckState())
    val manualCheckState: StateFlow<ManualCheckState> = _manualCheckState.asStateFlow()

    private var inFlightCheck: Deferred<ManualCheckResult>? = null
    private var manualCheck: Deferred<ManualCheckResult>? = null
    private var lastCheckAtMs: Long? = null
    private var downloadGeneration = 0L
    private var downloadJob: Job? = null

    init {
        UpdateCacheFiles.cleanupPartialDownloads(context.cacheDir)
        (context.applicationContext as? Application)?.registerActivityLifecycleCallbacks(
            object : Application.ActivityLifecycleCallbacks {
                override fun onActivityResumed(activity: Activity) { appForeground = true }
                override fun onActivityPaused(activity: Activity) { appForeground = false }
                override fun onActivityCreated(activity: Activity, state: Bundle?) = Unit
                override fun onActivityStarted(activity: Activity) = Unit
                override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) = Unit
                override fun onActivityStopped(activity: Activity) = Unit
                override fun onActivityDestroyed(activity: Activity) = Unit
            },
        )
    }

    private fun restoreState(): UpdateUiState {
        val manifestText = preferences.getString(KEY_MANIFEST, null)
        val info = manifestText?.let(UpdateInfoParser::parse)
            ?.takeIf { UpdateDecision.shouldOffer(installedVersionCode, it) }
        if (manifestText != null && info == null) preferences.edit().remove(KEY_MANIFEST).apply()

        val readyName = preferences.getString(KEY_READY_APK, null)
        val ready = readyName?.takeIf(::isReadyApkName)
            ?.takeIf { name -> info != null && readyApkVersion(name) == info.versionCode }
            ?.let { java.io.File(context.cacheDir, it) }
            ?.takeIf { it.isFile }
        if (readyName != null && ready == null) {
            readyName.takeIf(::isReadyApkName)?.let { java.io.File(context.cacheDir, it).delete() }
            preferences.edit().remove(KEY_READY_APK).apply()
        }
        readyApk = ready

        val incomplete = installAttemptId != null && installTargetVersion != null
        return UpdateUiState(
            available = info,
            readyToInstall = ready != null,
            installIncomplete = incomplete,
        )
    }

    private fun isReadyApkName(name: String): Boolean =
        name.matches(Regex("ai-control-update-[1-9][0-9]{0,9}-[0-9a-fA-F-]{36}\\.apk"))

    private fun readyApkVersion(name: String): Int? =
        Regex("ai-control-update-([1-9][0-9]{0,9})-[0-9a-fA-F-]{36}\\.apk")
            .matchEntire(name)?.groupValues?.get(1)?.toIntOrNull()

    /** Forceable common check; automatic foreground calls are rate limited separately. */
    suspend fun checkNow(): ManualCheckResult = withContext(Dispatchers.Main.immediate) {
        if (isBusy()) return@withContext ManualCheckResult.BUSY
        sharedCheck().await()
    }

    suspend fun checkManually(): ManualCheckResult = withContext(Dispatchers.Main.immediate) {
        if (isBusy()) {
            publishManualResult(ManualCheckResult.BUSY)
            return@withContext ManualCheckResult.BUSY
        }
        manualCheck?.let { return@withContext awaitManual(it) }
        _manualCheckState.value = _manualCheckState.value.copy(checking = true, pendingResult = null)
        val deferred = scope.async(start = CoroutineStart.LAZY) {
            var result = ManualCheckResult.CHECK_FAILED
            try {
                result = sharedCheck().await()
                result
            } finally {
                publishManualResult(result)
                manualCheck = null
            }
        }
        manualCheck = deferred
        deferred.start()
        awaitManual(deferred)
    }

    fun requestManualCheck() {
        scope.launch {
            if (_manualCheckState.value.checking || _manualCheckState.value.pendingResult != null) return@launch
            checkManually()
        }
    }

    fun acknowledgeManualCheckResult(resultId: Long) {
        scope.launch {
            val current = _manualCheckState.value
            if (current.resultId == resultId && current.pendingResult != null) {
                _manualCheckState.value = current.copy(pendingResult = null)
            }
        }
    }

    private fun sharedCheck(): Deferred<ManualCheckResult> {
        inFlightCheck?.let { return it }
        val check = scope.async(start = CoroutineStart.LAZY) {
            _state.value = _state.value.copy(checking = true)
            try {
                val body = try {
                    withTimeout(MANIFEST_TIMEOUT_MS) { fetchManifest() }
                } catch (_: TimeoutCancellationException) {
                    null
                }
                lastCheckAtMs = SystemClock.elapsedRealtime()
                val info = body?.let(UpdateInfoParser::parse)
                if (info == null) {
                    _state.value = _state.value.copy(checking = false, lastCheckFailed = true)
                    ManualCheckResult.CHECK_FAILED
                } else {
                    val result = if (UpdateDecision.shouldOffer(installedVersionCode, info)) {
                        val previousInfo = _state.value.available
                        if (previousInfo?.versionCode != info.versionCode || previousInfo.sha256 != info.sha256) {
                            readyApk?.delete()
                            readyApk = null
                            preferences.edit().remove(KEY_READY_APK).apply()
                            _state.value = _state.value.copy(readyToInstall = false)
                        }
                        preferences.edit().putString(KEY_MANIFEST, body).apply()
                        _state.value = _state.value.copy(
                            available = info, checking = false, lastCheckFailed = false,
                            errorMessage = null,
                        )
                        ManualCheckResult.UPDATE_AVAILABLE
                    } else {
                        val pendingAttempt = installAttemptId != null
                        if (!pendingAttempt) {
                            readyApk?.delete()
                            readyApk = null
                            preferences.edit().remove(KEY_READY_APK).remove(KEY_MANIFEST).apply()
                            _state.value = _state.value.copy(available = null, readyToInstall = false)
                        }
                        _state.value = _state.value.copy(checking = false, lastCheckFailed = false)
                        ManualCheckResult.UP_TO_DATE
                    }
                    result
                }
            } catch (error: CancellationException) {
                _state.value = _state.value.copy(checking = false)
                throw error
            } catch (_: Exception) {
                _state.value = _state.value.copy(checking = false, lastCheckFailed = true)
                ManualCheckResult.CHECK_FAILED
            } finally {
                inFlightCheck = null
            }
        }
        inFlightCheck = check
        check.start()
        return check
    }

    private suspend fun awaitManual(check: Deferred<ManualCheckResult>): ManualCheckResult = try {
        check.await()
    } catch (error: CancellationException) {
        if (!currentCoroutineContext().isActive) throw error
        ManualCheckResult.CHECK_FAILED
    } catch (_: Exception) {
        ManualCheckResult.CHECK_FAILED
    }

    private fun publishManualResult(result: ManualCheckResult) {
        val current = _manualCheckState.value
        _manualCheckState.value = current.copy(
            checking = false,
            pendingResult = result,
            resultId = current.resultId + 1,
        )
    }

    private fun isBusy(): Boolean =
        _state.value.downloadPercent != null || _state.value.installing

    private suspend fun fetchManifest(): String? = suspendCancellableCoroutine { continuation ->
        if (!UpdateUrlPolicy.validManifest(BuildConfig.UPDATE_MANIFEST_URL)) {
            continuation.resume(null)
            return@suspendCancellableCoroutine
        }
        val activeConnection = AtomicReference<java.net.HttpURLConnection?>()
        val cancelled = AtomicBoolean(false)
        val requestJob = scope.launch(Dispatchers.IO) {
            var connection: java.net.HttpURLConnection? = null
            try {
                val opened = (java.net.URL(BuildConfig.UPDATE_MANIFEST_URL).openConnection()
                    as java.net.HttpURLConnection).apply {
                    instanceFollowRedirects = false
                    useCaches = false
                    connectTimeout = MANIFEST_CONNECT_TIMEOUT_MS
                    readTimeout = MANIFEST_READ_TIMEOUT_MS
                    setRequestProperty("Accept", "application/json")
                }
                connection = opened
                activeConnection.set(opened)
                if (cancelled.get()) return@launch
                val body = if (opened.responseCode in 200..299) {
                    val length = opened.contentLengthLong
                    if (length > MAX_MANIFEST_BYTES) null
                    else opened.inputStream.use(::readManifestBody)
                } else {
                    null
                }
                continuation.resume(body)
            } catch (_: IOException) {
                continuation.resume(null)
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                continuation.resume(null)
            } finally {
                activeConnection.set(null)
                connection?.disconnect()
            }
        }
        continuation.invokeOnCancellation {
            cancelled.set(true)
            activeConnection.getAndSet(null)?.disconnect()
            requestJob.cancel()
        }
    }

    private fun readManifestBody(input: InputStream): String? {
        val bytes = ByteArrayOutputStream()
        val chunk = ByteArray(4096)
        while (true) {
            val count = input.read(chunk)
            if (count < 0) break
            if (count > MAX_MANIFEST_BYTES - bytes.size()) return null
            bytes.write(chunk, 0, count)
        }
        return try {
            Charsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes.toByteArray()))
                .toString()
        } catch (_: CharacterCodingException) {
            null
        }
    }

    /** User action downloads and verifies the APK. Installation is a separate action. */
    fun startDownload() {
        scope.launch {
            val info = _state.value.available ?: return@launch
            if (isBusy() || _state.value.installIncomplete) return@launch
            val generation = ++downloadGeneration
            readyApk?.delete()
            readyApk = null
            preferences.edit().remove(KEY_READY_APK).apply()
            _state.value = _state.value.copy(
                downloadPercent = 0, readyToInstall = false, errorMessage = null,
            )
            downloadJob = scope.launch {
                when (val result = downloader.download(info) { percent ->
                    scope.launch {
                        if (generation == downloadGeneration && downloadJob?.isActive == true) {
                            _state.value = _state.value.copy(downloadPercent = percent)
                        }
                    }
                }) {
                    is DownloadResult.Success -> {
                        if (generation == downloadGeneration) {
                            readyApk = result.file
                            preferences.edit().putString(KEY_READY_APK, result.file.name).apply()
                            _state.value = _state.value.copy(
                                downloadPercent = null, readyToInstall = true,
                                errorMessage = null,
                            )
                        } else {
                            result.file.delete()
                        }
                    }
                    is DownloadResult.Failure -> {
                        if (generation == downloadGeneration) {
                            _state.value = _state.value.copy(
                                downloadPercent = null,
                                errorMessage = context.getString(result.reason.toMessageRes()),
                            )
                        }
                    }
                }
            }
        }
    }

    fun cancelDownload() {
        scope.launch {
            if (_state.value.downloadPercent == null) return@launch
            downloadGeneration++
            downloadJob?.cancel()
            downloadJob = null
            _state.value = _state.value.copy(downloadPercent = null)
        }
    }

    /** Requires a second explicit user action after the verified download is ready. */
    fun startInstall() {
        scope.launch {
            if (isBusy() || _state.value.installIncomplete) return@launch
            val info = _state.value.available ?: return@launch
            val apk = readyApk ?: return@launch
            if (!apk.isFile) {
                _state.value = _state.value.copy(readyToInstall = false, errorMessage = context.getString(R.string.update_error_download))
                return@launch
            }
            if (!context.packageManager.canRequestPackageInstalls()) {
                _state.value = _state.value.copy(needsInstallPermission = true)
                return@launch
            }

            val attemptId = UUID.randomUUID().toString()
            if (!persistAttempt(attemptId, info.versionCode, NO_SESSION)) {
                _state.value = _state.value.copy(errorMessage = context.getString(R.string.update_error_install))
                return@launch
            }
            installAttemptId = attemptId
            installTargetVersion = info.versionCode
            installSessionId = null
            _state.value = _state.value.copy(
                installing = true, installIncomplete = false,
                needsInstallPermission = false, errorMessage = null,
            )

            val outcome = installer.install(apk, info, attemptId) { sessionId, committedAttempt, startedAt ->
                if (committedAttempt != installAttemptId) return@install
                installSessionId = sessionId
                installWaitStartedAtMs = startedAt
                if (!persistAttempt(committedAttempt, info.versionCode, sessionId)) {
                    _state.value = _state.value.copy(installing = false, installIncomplete = true)
                } else {
                    startInstallWatchdog(sessionId, committedAttempt, startedAt)
                }
            }
            if (outcome != InstallOutcome.STARTED && installAttemptId == attemptId) {
                clearInstallAttempt()
                _state.value = _state.value.copy(
                    installing = false,
                    installIncomplete = false,
                    readyToInstall = true,
                    errorMessage = context.getString(outcome.toMessageRes()),
                )
            }
        }
    }

    private fun persistAttempt(attemptId: String, versionCode: Int, sessionId: Int): Boolean =
        preferences.edit()
            .putString(KEY_INSTALL_ATTEMPT, attemptId)
            .putInt(KEY_INSTALL_TARGET, versionCode)
            .putInt(KEY_INSTALL_SESSION, sessionId)
            .commit()

    private fun startInstallWatchdog(sessionId: Int, attemptId: String, startedAt: Long) {
        installWatchdogJob?.cancel()
        installWatchdogJob = scope.launch {
            while (installSessionId == sessionId && installAttemptId == attemptId && _state.value.installing) {
                val now = SystemClock.elapsedRealtime()
                if (InstallWatchdog.isStuck(startedAt, now, resultReceived = false)) {
                    _state.value = _state.value.copy(
                        installing = false,
                        installIncomplete = true,
                        errorMessage = context.getString(R.string.update_error_unknown),
                    )
                    installWatchdogJob = null
                    return@launch
                }
                delay(minOf(1_000L, InstallWatchdog.TIMEOUT_MS - (now - startedAt)))
            }
        }
    }

    private fun stopInstallWatchdog() {
        installWatchdogJob?.cancel()
        installWatchdogJob = null
        installWaitStartedAtMs = null
    }

    fun onInstallPendingUserAction(sessionId: Int, attemptId: String): Boolean {
        if (installSessionId != sessionId || installAttemptId != attemptId || !_state.value.installing) return false
        val startedAt = SystemClock.elapsedRealtime()
        installWaitStartedAtMs = startedAt
        startInstallWatchdog(sessionId, attemptId, startedAt)
        return true
    }

    /** Keeps the platform confirmation until an explicit foreground user action. */
    fun onInstallPendingUserAction(sessionId: Int, attemptId: String, confirmIntent: Intent): Boolean {
        if (!onInstallPendingUserAction(sessionId, attemptId)) return false
        pendingConfirmation = Intent(confirmIntent).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        _state.value = _state.value.copy(needsUserConfirmation = true)
        return true
    }

    /** Called by the foreground UI's confirmation button; never invoked automatically. */
    fun confirmInstall(): Boolean {
        val confirmation = pendingConfirmation ?: return false
        if (!appForeground || installAttemptId == null) return false
        return try {
            context.startActivity(confirmation)
            pendingConfirmation = null
            _state.value = _state.value.copy(needsUserConfirmation = false)
            true
        } catch (_: android.content.ActivityNotFoundException) {
            false
        } catch (_: SecurityException) {
            false
        }
    }

    fun onInstallResult(sessionId: Int, attemptId: String, status: Int) {
        scope.launch {
            if (installSessionId != sessionId || installAttemptId != attemptId) return@launch
            pendingConfirmation = null
            stopInstallWatchdog()
            if (status == PackageInstaller.STATUS_SUCCESS) {
                val targetVersion = installTargetVersion ?: return@launch
                val currentVersion = withContext(Dispatchers.IO) { installedPackageVersionCode() }
                if (currentVersion != null && currentVersion >= targetVersion) {
                    readyApk?.delete()
                    readyApk = null
                    clearInstallAttempt()
                    preferences.edit().remove(KEY_READY_APK).remove(KEY_MANIFEST).apply()
                    _state.value = UpdateUiState()
                } else {
                    _state.value = _state.value.copy(
                        installing = false,
                        installIncomplete = true,
                        needsUserConfirmation = false,
                        errorMessage = context.getString(R.string.update_error_unknown),
                    )
                }
            } else {
                clearInstallAttempt()
                _state.value = _state.value.copy(
                    installing = false,
                    installIncomplete = false,
                    readyToInstall = readyApk?.isFile == true,
                    errorMessage = context.getString(R.string.update_error_install),
                )
            }
        }
    }

    private fun clearInstallAttempt() {
        stopInstallWatchdog()
        pendingConfirmation = null
        _state.value = _state.value.copy(needsUserConfirmation = false)
        installSessionId = null
        installAttemptId = null
        installTargetVersion = null
        preferences.edit()
            .remove(KEY_INSTALL_ATTEMPT)
            .remove(KEY_INSTALL_TARGET)
            .remove(KEY_INSTALL_SESSION)
            .apply()
    }

    /** Explicit recovery after timeout/restart; never starts an installer session. */
    fun reconcileInstall() {
        scope.launch { reconcileInstallNow() }
    }

    suspend fun reconcileInstallNow(): InstallReconciliation = withContext(Dispatchers.Main.immediate) {
        val target = installTargetVersion ?: return@withContext InstallReconciliation.NONE
        val sessionId = installSessionId
        val snapshot = withContext(Dispatchers.IO) {
            val installed = installedPackageVersionCode()
            val sessionActive = try {
                context.packageManager.packageInstaller.mySessions.any { session ->
                    if (sessionId != null) session.sessionId == sessionId
                    else session.appPackageName == context.packageName
                }
            } catch (_: Exception) {
                null
            }
            installed to sessionActive
        }
        val installed = snapshot.first
        val sessionActive = snapshot.second
        when {
            installed != null && installed >= target -> {
                readyApk?.delete()
                readyApk = null
                clearInstallAttempt()
                preferences.edit().remove(KEY_READY_APK).remove(KEY_MANIFEST).apply()
                _state.value = UpdateUiState()
                InstallReconciliation.INSTALLED
            }
            sessionActive == true -> {
                _state.value = _state.value.copy(
                    installing = false,
                    installIncomplete = true,
                    errorMessage = context.getString(R.string.update_error_unknown),
                )
                InstallReconciliation.SESSION_ACTIVE
            }
            installed != null && installed < target && sessionActive == false -> {
                clearInstallAttempt()
                _state.value = _state.value.copy(
                    installing = false,
                    installIncomplete = false,
                    needsUserConfirmation = false,
                    readyToInstall = readyApk?.isFile == true,
                    errorMessage = context.getString(R.string.update_error_install),
                )
                InstallReconciliation.NOT_INSTALLED
            }
            else -> {
                _state.value = _state.value.copy(
                    installing = false,
                    installIncomplete = true,
                    errorMessage = context.getString(R.string.update_error_unknown),
                )
                InstallReconciliation.UNKNOWN
            }
        }
    }

    private fun installedPackageVersionCode(): Long? = try {
        val info: PackageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.longVersionCode else @Suppress("DEPRECATION") info.versionCode.toLong()
    } catch (_: Exception) {
        null
    }

    fun refreshInstallPermissionState() {
        scope.launch {
            val needsPermission = _state.value.readyToInstall &&
                !context.packageManager.canRequestPackageInstalls()
            _state.value = _state.value.copy(needsInstallPermission = needsPermission)
        }
    }

    /** Foreground-only automatic check. Returning from settings never starts installation. */
    fun onAppResumed() {
        refreshInstallPermissionState()
        scope.launch {
            val now = SystemClock.elapsedRealtime()
            if (!isBusy() && (lastCheckAtMs == null || now - lastCheckAtMs!! >= RESUME_CHECK_INTERVAL_MS)) {
                checkNow()
            }
        }
    }

    fun installPermissionSettingsIntent(): Intent =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    /** True means the UI should open the system settings screen; this never installs. */
    fun continueOrNeedsSettings(): Boolean {
        val needsSettings = !context.packageManager.canRequestPackageInstalls()
        scope.launch { _state.value = _state.value.copy(needsInstallPermission = needsSettings) }
        return needsSettings
    }

    private fun FailureReason.toMessageRes(): Int = when (this) {
        FailureReason.NETWORK, FailureReason.INCOMPLETE -> R.string.update_error_network
        FailureReason.CHECKSUM_MISMATCH -> R.string.update_error_checksum
        FailureReason.INVALID_URL -> R.string.update_error_download
        FailureReason.TOO_LARGE -> R.string.update_error_too_large
    }

    private fun InstallOutcome.toMessageRes(): Int = when (this) {
        InstallOutcome.CHECKSUM_MISMATCH -> R.string.update_error_checksum
        InstallOutcome.INVALID_PACKAGE -> R.string.update_error_package
        InstallOutcome.STARTED, InstallOutcome.FAILED -> R.string.update_error_install
    }

    companion object {
        private const val PREFS_NAME = "android_update_metadata"
        private const val KEY_MANIFEST = "manifest_json"
        private const val KEY_READY_APK = "ready_apk_name"
        private const val KEY_INSTALL_ATTEMPT = "install_attempt_id"
        private const val KEY_INSTALL_TARGET = "install_target_version"
        private const val KEY_INSTALL_SESSION = "install_session_id"
        private const val NO_SESSION = -1
        private const val MANIFEST_CONNECT_TIMEOUT_MS = 10_000
        private const val MANIFEST_READ_TIMEOUT_MS = 10_000
        private const val MANIFEST_TIMEOUT_MS = 20_000L
        private const val MAX_MANIFEST_BYTES = 16 * 1024L
        private const val RESUME_CHECK_INTERVAL_MS = 5 * 60 * 1000L
    }
}
