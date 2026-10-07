package ru.dewil.aicontrol.updater

data class UpdateUiState(
    val available: UpdateInfo? = null,
    val checking: Boolean = false,
    val lastCheckFailed: Boolean = false,
    /** null while idle; otherwise download percent in 0..100. */
    val downloadPercent: Int? = null,
    val readyToInstall: Boolean = false,
    val installing: Boolean = false,
    /** Installation result is unknown and requires explicit reconciliation. */
    val installIncomplete: Boolean = false,
    val needsInstallPermission: Boolean = false,
    /** A package installer confirmation intent is waiting for an explicit foreground action. */
    val needsUserConfirmation: Boolean = false,
    val errorMessage: String? = null,
)
