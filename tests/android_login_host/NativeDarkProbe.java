package ru.dewil.aicontrol;
import android.view.View;
import android.widget.EditText;
import android.widget.TextView;
import java.lang.reflect.Method;
/** INV-AND-16: independent actual Activity hierarchy; synthetic login only. */
public final class NativeDarkProbe {
 static double luminance(int color){double sum=0;double[] weights={.2126,.7152,.0722};for(int i=0;i<3;i++){double c=((color>>(16-8*i))&255)/255.;sum+=weights[i]*(c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4));}return sum;}
 static void checkScreen(MainActivity activity,String name){
  View root=activity.getWindow().getDecorView();
  LoginLifecycleProbe.check(root.getBackgroundColor()==0xff141414,name+" native root remains light");
  for(View view:LoginLifecycleProbe.flatten(root)) {
   if(view instanceof android.view.ViewGroup && view.getBackgroundColor()!=0)LoginLifecycleProbe.check(view.getBackgroundColor()==0xff141414,name+" native container remains light");
   if(view instanceof TextView){TextView t=(TextView)view;int background=view.getBackgroundColor();if(background==0)background=0xff141414;
    double contrast=(luminance(t.getCurrentTextColor())+.05)/(luminance(background)+.05);
    LoginLifecycleProbe.check(contrast>=4.5,name+" text lacks4.5:1 contrast");
    if(view instanceof EditText)LoginLifecycleProbe.check((luminance(t.getCurrentHintTextColor())+.05)/(luminance(background)+.05)>=4.5,name+" hint lacks4.5:1 contrast");
   }
  }
 }
 public static void main(String[] args)throws Exception{
  MainActivity activity=new MainActivity();try{activity.onCreate(null);activity.onStart();checkScreen(activity,"login");
   Method wait=MainActivity.class.getDeclaredMethod("showWait",String.class);wait.setAccessible(true);wait.invoke(activity,"Synthetic wait");checkScreen(activity,"wait");
   Method failure=MainActivity.class.getDeclaredMethod("showFailure",String.class,boolean.class);failure.setAccessible(true);failure.invoke(activity,"Synthetic error",true);checkScreen(activity,"error");
   System.out.println("PASS dark native login/wait/error");
  }finally{activity.onStop();activity.onDestroy();}
 }
}
