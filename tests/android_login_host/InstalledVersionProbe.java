package ru.dewil.aicontrol;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.view.View;
import android.widget.TextView;
/** INV-AND-17: actual UpdatesActivity with synthetic own-package metadata. */
public final class InstalledVersionProbe {
 static void expect(UpdatesActivity activity,String expected){boolean found=false;for(View view:LoginLifecycleProbe.flatten(activity.getWindow().getDecorView()))if(view instanceof TextView && expected.contentEquals(((TextView)view).getText()))found=true;LoginLifecycleProbe.check(found,"Installed-version label differs from local package metadata");}
 public static void main(String[] args)throws Exception{
  PackageInfo info=new PackageInfo();info.versionName="0.1.4";info.versionCode=5;if(android.os.Build.VERSION.SDK_INT>=28)info.setLongVersionCode(4294967302L);
  PackageManager.fixture=info;PackageManager.failure=false;
  UpdatesActivity activity=new UpdatesActivity();try{
   if(args[0].equals("unknown")){PackageManager.failure=true;}
   else if(args[0].equals("empty")){info.versionName="";}
   else if(args[0].equals("missing")){info.versionName=null;}
   else if(args[0].equals("invalid")){info.versionCode=0;info.setLongVersionCode(0);}
   activity.onCreate(null);
   String expected=(args[0].equals("unknown")||args[0].equals("empty")||args[0].equals("invalid")||args[0].equals("missing"))?"Установлена: неизвестно":android.os.Build.VERSION.SDK_INT>=28?"Установлена: 0.1.4 (сборка 4294967302)":"Установлена: 0.1.4 (сборка 5)";
   if(!args[0].equals("observer"))expect(activity,expected);


   activity.getApplication().getUpdateRepository().available=new ru.dewil.aicontrol.updater.UpdateInfo("0.1.5");
   activity.onStart();LoginLifecycleProbe.callback(activity,"onResume");android.os.Handler.runPosted();expect(activity,expected);
   LoginLifecycleProbe.check(PackageManager.queriedPackage.equals(activity.getPackageName()),"Metadata lookup is not own installed package");
   LoginLifecycleProbe.check(activity.getWindow().getDecorView().getBackgroundColor()==0xff141414,"Updates native screen remains light");
   boolean controls=false;for(View view:LoginLifecycleProbe.flatten(activity.getWindow().getDecorView()))if(view instanceof TextView && "Проверить обновления".contentEquals(((TextView)view).getText()))controls=view.isEnabled();LoginLifecycleProbe.check(controls,"Package metadata failure disabled independent updater controls");
   LoginLifecycleProbe.callback(activity,"onPause");activity.onStop();
   if(args[0].equals("reopen")){PackageInfo newer=new PackageInfo();newer.versionName="0.1.6";newer.versionCode=7;newer.setLongVersionCode(7);PackageManager.fixture=newer;UpdatesActivity fresh=new UpdatesActivity();try{fresh.onCreate(null);expect(fresh,"Установлена: 0.1.6 (сборка 7)");}finally{fresh.onDestroy();}}
   System.out.println("PASS installed label "+args[0]);
  }finally{activity.onDestroy();}
 }
}
