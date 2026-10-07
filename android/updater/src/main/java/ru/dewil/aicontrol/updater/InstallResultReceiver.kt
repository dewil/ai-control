package ru.dewil.aicontrol.updater

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build

/** System-only receiver; both session and app attempt must match before state changes. */
class InstallResultReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val sessionId = intent.getIntExtra(PackageInstaller.EXTRA_SESSION_ID, -1)
        val attemptId = intent.getStringExtra(EXTRA_ATTEMPT_ID) ?: return
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        val owner = context.applicationContext as? UpdateRepositoryOwner ?: return

        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            val confirmIntent = extractConfirmIntent(intent) ?: run {
                owner.updateRepository.onInstallResult(sessionId, attemptId, PackageInstaller.STATUS_FAILURE)
                return
            }
            owner.updateRepository.onInstallPendingUserAction(sessionId, attemptId, confirmIntent)
            return
        }

        owner.updateRepository.onInstallResult(sessionId, attemptId, status)
    }

    private fun extractConfirmIntent(intent: Intent): Intent? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(Intent.EXTRA_INTENT)
        }

    companion object {
        const val EXTRA_ATTEMPT_ID = "ru.dewil.aicontrol.updater.extra.ATTEMPT_ID"
    }
}
