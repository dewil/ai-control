package ru.dewil.aicontrol;

import android.view.View;
import android.view.ViewGroup;
import android.view.Gravity;
import android.webkit.WebView;
import android.widget.FrameLayout;
import android.widget.TextView;
import java.lang.reflect.Method;
import java.util.List;

/** INV-AND-15: frozen independent viewport oracle; real Activity, synthetic edges. */
public final class CompactUpdatesProbe {
    static void call(MainActivity activity,String name) throws Exception {
        Method method=MainActivity.class.getDeclaredMethod(name);method.setAccessible(true);method.invoke(activity);
    }
    static void check(boolean value,String message) {if(!value)throw new AssertionError(message);}
    static WebView page(MainActivity activity) {
        for(View view:LoginLifecycleProbe.flatten(activity.getWindow().getDecorView()))if(view instanceof WebView)return (WebView)view;
        throw new AssertionError("Authenticated WebView missing");
    }
    static TextView update(MainActivity activity) {
        TextView found=null;
        for(View view:LoginLifecycleProbe.flatten(activity.getWindow().getDecorView())) {
            if(view instanceof TextView && (((TextView)view).getText().toString().equals("Обновления") || ((TextView)view).getText().toString().startsWith("Доступно обновление "))) {
                check(found==null,"Duplicate authenticated updates control");found=(TextView)view;
            }
        }
        check(found!=null,"Authenticated updates entry missing");return found;
    }
    public static void main(String[] args) throws Exception {
        MainActivity activity=new MainActivity();
        try {
            activity.onCreate(null);activity.onStart();LoginLifecycleProbe.callback(activity,"onResume");
            call(activity,"ensureWeb");call(activity,"hideOverlay");
            WebView web=page(activity);TextView updates=update(activity);
            FrameLayout.LayoutParams viewport=(FrameLayout.LayoutParams)web.getLayoutParams();
            FrameLayout.LayoutParams control=(FrameLayout.LayoutParams)updates.getLayoutParams();
            int target=(int)(48*activity.getResources().getDisplayMetrics().density);
            if(args[0].equals("viewport")) {
                check(viewport.topMargin==0,"Updates still reserves a top WebView inset");
                check(viewport.bottomMargin==target,"WebView does not reserve the accessible footer height");
                check(viewport.width==ViewGroup.LayoutParams.MATCH_PARENT && viewport.height==ViewGroup.LayoutParams.MATCH_PARENT,"WebView does not fill remaining native content");
                check(control.width==ViewGroup.LayoutParams.WRAP_CONTENT,"Updates remains full-width instead of compact");
                check(control.height==target,"Updates touch target is not48dp");
                check((control.gravity & Gravity.VERTICAL_GRAVITY_MASK)==Gravity.BOTTOM,"Updates is not at bottom");
                check((control.gravity & Gravity.RELATIVE_HORIZONTAL_GRAVITY_MASK)==Gravity.END,"Updates is not at end");
                // Independent geometry oracle for native content800x600. Android
                // FrameLayout MATCH_PARENT sizing subtracts declared margins.
                int pageBottom=600-viewport.bottomMargin;
                int footerTop=600-control.height;
                check(pageBottom<=footerTop,"Footer overlays web controls");
            } else if(args[0].equals("palette")) {
                check(updates.getBackgroundColor()==0xff141414,"Footer is not dark#141414");
                int rgb=updates.getCurrentTextColor();
                check(((rgb>>16)&255)+((rgb>>8)&255)+(rgb&255)>=600,"Footer text is not light/readable");
                check(updates.isClickable()&&updates.isFocusable(),"Updates is not accessible by click/focus");
                check(activity.getWindow().statusBarColor==0xff141414 && activity.getWindow().navigationBarColor==0xff141414,"Native system bars do not match panel");
                check(!activity.getWindow().lightStatus && !activity.getWindow().lightNavigation,"Native bar icons request dark mode");
            } else {
                call(activity,"ensureWeb");
                check(web==page(activity)&&updates==update(activity),"Repeated ensureWeb replaces page/control");
                updates.performClick();
                check(activity.lastIntent!=null && activity.lastIntent.destination==UpdatesActivity.class,"Explicit update click opens wrong destination");
                activity.getApplication().getUpdateRepository().available=new ru.dewil.aicontrol.updater.UpdateInfo();
                android.os.Handler.runPosted();
                check(update(activity)==updates,"Update notice replaces compact entry");
                check(updates.getText().toString().equals("Доступно обновление fixture"),"Available-version notice is lost");
                check(web.getLayoutParams()==viewport && viewport.topMargin==0 && viewport.bottomMargin==target,"Badge changes viewport");
                call(activity,"destroyPage");
                for(View view:LoginLifecycleProbe.flatten(activity.getWindow().getDecorView()))
                    check(!(view instanceof WebView) && view!=updates,"destroyPage retained web/control");
            }
            System.out.println("PASS compact updates "+args[0]);
        } finally {LoginLifecycleProbe.callback(activity,"onPause");activity.onStop();activity.onDestroy();}
    }
}
