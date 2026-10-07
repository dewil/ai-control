package ru.dewil.aicontrol

import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.combine
import ru.dewil.aicontrol.updater.ManualCheckResult
import ru.dewil.aicontrol.updater.UpdateRepositoryOwner

/** Explicit download/install controls, independent of panel credentials. */
class UpdatesActivity : ComponentActivity() {
    private val repository get() = (application as UpdateRepositoryOwner).updateRepository
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var observing: Job? = null
    private var manualMessage: String? = null
    private lateinit var status: TextView
    private lateinit var check: Button
    private lateinit var download: Button
    private lateinit var install: Button
    private lateinit var cancel: Button
    private lateinit var permission: Button
    private lateinit var confirm: Button
    private lateinit var reconcile: Button
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val box = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(32,64,32,32) }
        setContentView(box)
        status=TextView(this).apply { textSize=18f };box.addView(status)
        fun button(text:String,action:()->Unit)=Button(this).apply { this.text=text;setOnClickListener { action() };box.addView(this) }
        check=button("Проверить обновления") { manualMessage=null;repository.requestManualCheck() }
        download=button("Скачать APK") { repository.startDownload() }
        cancel=button("Отменить скачивание") { repository.cancelDownload() }
        permission=button("Разрешить установку") { startActivity(repository.installPermissionSettingsIntent()) }
        install=button("Установить") { repository.startInstall() }
        confirm=button("Подтвердить установку в Android") { repository.confirmInstall() }
        reconcile=button("Проверить результат установки") { scope.launch { repository.reconcileInstall() } }
        button("Вернуться в панель") { finish() }
    }
    override fun onStart() {
        super.onStart();repository.onAppResumed()
        observing=scope.launch {
            combine(repository.state,repository.manualCheckState) { state,manual -> state to manual }.collect { (state,manual) ->
                manual.pendingResult?.let { result ->
                    manualMessage=when(result){
                        ManualCheckResult.UPDATE_AVAILABLE -> "Доступно обновление."
                        ManualCheckResult.UP_TO_DATE -> "Установлена последняя версия."
                        ManualCheckResult.CHECK_FAILED -> "Не удалось проверить обновления. Повторите подключение."
                        ManualCheckResult.BUSY -> "Операция уже выполняется. Дождитесь ее завершения."
                    }
                }
                status.text=buildString {
                    append("ai-control ").append(BuildConfig.VERSION_NAME)
                    when {
                        state.installIncomplete -> append("\nРезультат установки пока неизвестен.")
                        state.installing -> append("\nОжидаем подтверждение Android.")
                        state.downloadPercent!=null -> append("\nСкачивание: ").append(state.downloadPercent).append("%")
                        state.readyToInstall -> append("\nAPK проверен и готов к установке.")
                        state.available!=null -> append("\nДоступна версия ").append(state.available?.versionName)
                        state.checking -> append("\nПроверяем обновления…")
                        state.lastCheckFailed -> append("\nНе удалось проверить обновления. Повторите подключение.")
                        else -> append("\nНажмите «Проверить обновления».")
                    }
                    state.errorMessage?.let { append("\n").append(it) }
                    manualMessage?.let { append("\n").append(it) }
                }
                val idle=!state.checking&&!state.installing&&state.downloadPercent==null&&!state.installIncomplete
                check.isEnabled=idle&&!manual.checking
                if(manual.pendingResult!=null)repository.acknowledgeManualCheckResult(manual.resultId)
                download.visibility=if(state.available!=null&&!state.readyToInstall) android.view.View.VISIBLE else android.view.View.GONE
                download.isEnabled=idle
                cancel.visibility=if(state.downloadPercent!=null) android.view.View.VISIBLE else android.view.View.GONE
                install.visibility=if(state.readyToInstall) android.view.View.VISIBLE else android.view.View.GONE
                install.isEnabled=idle&&!state.needsInstallPermission
                permission.visibility=if(state.needsInstallPermission) android.view.View.VISIBLE else android.view.View.GONE
                confirm.visibility=if(state.needsUserConfirmation) android.view.View.VISIBLE else android.view.View.GONE
                reconcile.visibility=if(state.installIncomplete) android.view.View.VISIBLE else android.view.View.GONE
            }
        }
    }
    override fun onStop(){observing?.cancel();super.onStop()}
    override fun onDestroy(){scope.cancel();super.onDestroy()}
}
