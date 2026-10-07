package ru.dewil.aicontrol

import android.app.Application
import ru.dewil.aicontrol.updater.UpdateRepository
import ru.dewil.aicontrol.updater.UpdateRepositoryOwner

class ControlApplication : Application(), UpdateRepositoryOwner {
    override val updateRepository by lazy { UpdateRepository(this, BuildConfig.VERSION_CODE) }
}
