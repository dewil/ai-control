package ru.dewil.aicontrol.updater;
public class UpdateRepository {
public UpdateInfo available;
private kotlinx.coroutines.flow.MutableStateFlow<UpdateUiState> state=kotlinx.coroutines.flow.StateFlowKt.MutableStateFlow(new UpdateUiState(null,false,true,null,false,false,false,false,false,"Synthetic offline"));
private kotlinx.coroutines.flow.MutableStateFlow<ManualCheckState> manual=kotlinx.coroutines.flow.StateFlowKt.MutableStateFlow(new ManualCheckState(false,null,0));
public kotlinx.coroutines.flow.StateFlow<UpdateUiState> getState(){if(state.getValue().getAvailable()!=available)state.setValue(new UpdateUiState(available,false,true,null,false,false,false,false,false,"Synthetic offline"));return state;}
public kotlinx.coroutines.flow.StateFlow<ManualCheckState> getManualCheckState(){return manual;}
public void onAppResumed(){}public void requestManualCheck(){}public void acknowledgeManualCheckResult(long id){}public void startDownload(){}public void cancelDownload(){}public android.content.Intent installPermissionSettingsIntent(){return new android.content.Intent(null,ru.dewil.aicontrol.UpdatesActivity.class);}public void startInstall(){}public boolean confirmInstall(){return false;}public void reconcileInstall(){}
}
