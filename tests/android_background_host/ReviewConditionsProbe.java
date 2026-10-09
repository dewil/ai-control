package ru.dewil.aicontrol;

import android.os.Handler;
import android.webkit.WebView;

/** Review-condition delta only; frozen RED probe remains unchanged. */
public final class ReviewConditionsProbe {
 public static void main(String[] args){try{run(args[0]);System.out.println("PASS review condition "+args[0]);System.exit(0);}catch(Throwable error){error.printStackTrace();System.exit(1);}}
 static void check(boolean value,String message){BackgroundProbe.check(value,message);}
 static int pauses(){return BackgroundProbe.count("pauseTimers");}
 static void run(String scenario)throws Exception {
  MainActivity activity=BackgroundProbe.login();WebView page=BackgroundProbe.page();
  WebView.events.clear();page.evals.clear();BackgroundProbe.pause(activity);
  if(scenario.equals("unconfirmed-return")){
   Handler.advance(500);check(pauses()==1,"INV-BATT-05: missing callback must establish timer pause at blocktime+500ms");
   int admissions=AuthHttp.calls,evaluations=page.evals.size(),loads=BackgroundProbe.count("load");
   activity.onStop();activity.onStart();BackgroundProbe.lifecycle(activity,"onResume");Handler.runPosted();Handler.advance(65000);
   Thread.sleep(25);Handler.runPosted();
   check(AuthHttp.calls==admissions,"blocked_unconfirmed onResume started forbidden native admission");
   check(page.evals.size()==evaluations,"blocked_unconfirmed onResume started forbidden production reprobe");
   check(BackgroundProbe.count("load")==loads&&!page.destroyed,"blocked_unconfirmed return reloaded/destroyed retained page");
   check(page.getSettings().blocked,"blocked_unconfirmed return reopened native network gate");return;
  }
  check(page.evals.size()==1,"INV-BATT-01: one suspend command required before callback-fence scenario");
  WebView.Eval pending=page.evals.get(0);long serial=BackgroundProbe.serial(pending);
  if(scenario.equals("invalid-at400")){
   Handler.advance(400);pending.callback.onReceiveValue("null");Handler.runPosted();
   Handler.advance(99);check(pauses()==0,"Suspend branch paused before original 500ms deadline");
   Handler.advance(1);check(pauses()==1,"Invalid callback reset deadline instead of keeping blocktime+500ms");return;
  }
  if(scenario.equals("late-ack-before-timer")){
   // Model an overdue UI timer whose runnable has not been serviced. The next
   // queued eval result must be rejected using monotonic time, not timer state.
   Handler.now+=501;pending.callback.onReceiveValue(BackgroundProbe.ack(serial));
   check(pauses()==0,"ACK received after blocktime+500ms was accepted before overdue timer runnable");
   Handler.runPosted();check(pauses()==1,"Rejected late ACK canceled the independent overdue deadline");return;
  }
  if(scenario.equals("navigation-old-ack")||scenario.equals("renderer-old-ack")){
   Handler.advance(100);check(page.client!=null,"Missing WebView lifecycle client");
   if(scenario.equals("renderer-old-ack")){
    page.client.onRenderProcessGone(page,new android.webkit.RenderProcessGoneDetail(){public boolean didCrash(){return true;}public int rendererPriorityAtExit(){return 0;}});
    Thread.sleep(25);
   }else page.client.onPageStarted(page,page.url,null);
   Handler.runPosted();
   int paused=pauses(),events=WebView.events.size();
   pending.callback.onReceiveValue(BackgroundProbe.ack(serial));Handler.runPosted();
   check(pauses()==paused,"Old navigation suspend ACK changed current navigation timer ownership");
   check(WebView.events.size()==events,"Old navigation ACK changed current WebView state");
   if(!page.destroyed)check(page.getSettings().blocked,"Old navigation ACK reopened native dispatch");return;
  }
  throw new AssertionError("Unknown review-condition scenario "+scenario);
 }
}
