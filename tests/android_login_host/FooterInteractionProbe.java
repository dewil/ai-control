package ru.dewil.aicontrol;
import android.widget.TextView;
/** INV-AND-16 / ANDROID-UX-SOURCE-01: actual setter effects on themed footer. */
public final class FooterInteractionProbe {
 public static void main(String[] args)throws Exception{
  MainActivity activity=new MainActivity();try{activity.onCreate(null);activity.onStart();LoginLifecycleProbe.callback(activity,"onResume");CompactUpdatesProbe.call(activity,"ensureWeb");CompactUpdatesProbe.call(activity,"hideOverlay");
   TextView entry=CompactUpdatesProbe.update(activity);
   LoginLifecycleProbe.check(entry.hasStatefulBackground(),"Authenticated footer replaces focus/pressed feedback with a flat background");
   LoginLifecycleProbe.check(entry.isClickable()&&entry.isFocusable(),"Footer loses keyboard/click accessibility");
   android.widget.FrameLayout.LayoutParams layout=(android.widget.FrameLayout.LayoutParams)entry.getLayoutParams();
   LoginLifecycleProbe.check(layout.height>=48*activity.getResources().getDisplayMetrics().density,"Footer touch target shrinks below48dp");
   System.out.println("PASS footer interaction state and48dp");
  }finally{LoginLifecycleProbe.callback(activity,"onPause");activity.onStop();activity.onDestroy();}
 }
}
