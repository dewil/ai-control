package ru.dewil.aicontrol.updater

/** Application owns updater state; the explicit installer receiver accesses it through this interface. */
interface UpdateRepositoryOwner {
    val updateRepository: UpdateRepository
}
