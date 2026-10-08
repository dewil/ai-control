package android.app;
public class Application extends android.content.Context implements ru.dewil.aicontrol.updater.UpdateRepositoryOwner { private ru.dewil.aicontrol.updater.UpdateRepository repo=new ru.dewil.aicontrol.updater.UpdateRepository();public ru.dewil.aicontrol.updater.UpdateRepository getUpdateRepository(){return repo;} }
