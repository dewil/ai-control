package android.app;
public class Application extends android.content.Context implements ru.dewil.aicontrol.updater.UpdateRepositoryOwner { private ru.dewil.aicontrol.updater.Repository repo=new ru.dewil.aicontrol.updater.Repository();public ru.dewil.aicontrol.updater.Repository getUpdateRepository(){return repo;} }
