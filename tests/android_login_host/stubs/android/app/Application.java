package android.app;
public class Application extends android.content.Context implements ru.dewil.aicontrol.updater.UpdateRepositoryOwner { public ru.dewil.aicontrol.updater.Repository getUpdateRepository(){return new ru.dewil.aicontrol.updater.Repository();} }
