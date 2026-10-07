package ru.dewil.aicontrol.policy

/** INV-AUTHAND-05: late admissions cannot undo stop/logout/denial. */
class AuthGate {
    private var generation = 0L
    private var foreground = false
    private var blocked = false
    @Synchronized fun begin(): Long { foreground = true; return ++generation }
    @Synchronized fun stop() { foreground = false; generation++ }
    @Synchronized fun logout() { blocked = true; generation++ }
    @Synchronized fun deny() { blocked = true; generation++ }
    @Synchronized fun resetAfterExplicitLogin(): Long {
        blocked = false; foreground = true; return ++generation
    }
    @Synchronized fun canApply(generation: Long): Boolean =
        foreground && !blocked && this.generation == generation
}
