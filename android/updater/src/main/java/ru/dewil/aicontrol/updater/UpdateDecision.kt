package ru.dewil.aicontrol.updater

/** Чистая Kotlin-логика: сравнение версий, ничего больше. */
object UpdateDecision {

    /** Предлагать обновление, только если версия на сервере строго новее установленной. */
    fun shouldOffer(installedVersionCode: Int, remote: UpdateInfo): Boolean =
        remote.versionCode > installedVersionCode
}
