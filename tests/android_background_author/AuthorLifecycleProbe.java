package ru.dewil.aicontrol;
import android.os.Handler;
import android.webkit.*;
import org.json.JSONObject;
/** Public callbacks/interceptor and controlled eval replies; no production field access. */
public final class AuthorLifecycleProbe {
 static void check(boolean value,String message){BackgroundProbe.check(value,message);}
 static WebView.Eval latest(WebView page){return page.evals.get(page.evals.size()-1);}
 static String json(JSONObject value){return JSONObject.quote(value.toString());}
 static void start(WebView.Eval command)throws Exception{command.callback.onReceiveValue(json(new JSONObject().put("started",true)));}
 static void ready(WebView.Eval command,String phase)throws Exception{long serial=BackgroundProbe.serial(command);start(command);Handler.advance(100);latest(BackgroundProbe.page()).callback.onReceiveValue(json(new JSONObject().put("serial",serial).put("phase",phase).put("ok",true)));}
 static WebView.Eval preflight(MainActivity activity)throws Exception{WebView page=BackgroundProbe.page();page.client.onPageFinished(page,page.url);WebView.Eval suspend=latest(page);check(suspend.script.contains("aiControlAndroidSuspend"),"Initial protocol check must call structured preflight");suspend.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(suspend)));return latest(page);}
 static void active(MainActivity activity)throws Exception{WebView page=BackgroundProbe.page();WebView.Eval admit=preflight(activity);ready(admit,"admit");WebView.Eval activate=latest(page);ready(activate,"activate");}
 static boolean allowed(String path,String method){WebView page=BackgroundProbe.page();return page.client.shouldInterceptRequest(page,BackgroundProbe.request(path,method))==null;}
 static android.widget.Button retry(MainActivity activity){for(android.view.View view:BackgroundProbe.flatten(activity.getWindow().getDecorView()))if(view instanceof android.widget.Button&&"Повторить".contentEquals(((android.widget.Button)view).getText()))return (android.widget.Button)view;return null;}
 static void waitRetry(MainActivity activity)throws Exception{long until=System.nanoTime()+2_000_000_000L;while(retry(activity)==null&&System.nanoTime()<until){Handler.runPosted();Thread.sleep(2);}check(retry(activity)!=null,"Expected explicit transport retry");}
 static void waitCalls(int count)throws Exception{long until=System.nanoTime()+2_000_000_000L;while(AuthHttp.calls<count&&System.nanoTime()<until){Handler.runPosted();Thread.sleep(2);}Handler.runPosted();check(AuthHttp.calls>=count,"Expected fresh native admission");}
 static void waitCookie()throws Exception{long until=System.nanoTime()+2_000_000_000L;while(CookieManager.pending==null&&System.nanoTime()<until){Handler.runPosted();Thread.sleep(2);}check(CookieManager.pending!=null,"Native cookie callback prerequisite");}
 public static void main(String[] args){try{run(args[0]);System.out.println("PASS author "+args[0]);System.exit(0);}catch(Throwable error){error.printStackTrace();System.exit(1);}}
 static void run(String scenario)throws Exception{
  MainActivity activity=BackgroundProbe.login();WebView page=BackgroundProbe.page();
  if(scenario.equals("two-phase")){
   WebView.Eval admit=preflight(activity);check(admit.script.contains("phase:'admit'"),"Missing admit phase");
   check(allowed("/api/session","GET"),"Native ADMITTING denies fresh session GET");
   check(!allowed("/api/session-send","POST")&&!allowed("/api/session-events","GET"),"ADMITTING exposes observation/mutation dispatch");
   ready(admit,"admit");WebView.Eval activate=latest(page);
   check(activate.script.contains("phase:'activate'")&&activate.script.contains("admissionSerial:"+BackgroundProbe.serial(admit)),"Activation is not bound to admitted serial");
   check(allowed("/api/session-send","POST"),"Native ACTIVE must precede page activation command");ready(activate,"activate");return;
  }
  if(scenario.equals("admit-timeout")){
   WebView.Eval admit=preflight(activity);int pauses=BackgroundProbe.count("pauseTimers");Handler.advance(10000);
   WebView.Eval cancel=latest(page);check(cancel!=admit&&cancel.script.contains("aiControlAndroidSuspend"),"Admission timeout did not cancel via structured suspend");
   check(BackgroundProbe.serial(cancel)>BackgroundProbe.serial(admit),"Cancellation serial did not fence admission");
   check(BackgroundProbe.count("pauseTimers")==pauses,"Admission timeout paused before cancellation ACK/deadline");
   cancel.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(cancel)));check(BackgroundProbe.count("pauseTimers")==pauses+1,"Cancellation ACK did not pause");
   int events=WebView.events.size();start(admit);check(WebView.events.size()==events&&!allowed("/api/session-send","POST"),"Late admission callback reopened dispatch");return;
  }
  if(scenario.equals("activate-timeout")){
   WebView.Eval admit=preflight(activity);ready(admit,"admit");WebView.Eval activate=latest(page);int pauses=BackgroundProbe.count("pauseTimers");
   Handler.advance(500);WebView.Eval cancel=latest(page);check(cancel!=activate&&BackgroundProbe.serial(cancel)>BackgroundProbe.serial(activate),"Activation deadline did not start fenced cancellation");
   check(!allowed("/api/session-send","POST"),"Activation failure kept native ACTIVE");Handler.advance(499);check(BackgroundProbe.count("pauseTimers")==pauses,"Cancellation waited less than500ms");Handler.advance(1);check(BackgroundProbe.count("pauseTimers")==pauses+1,"Independent cancellation deadline absent");return;
  }
  if(scenario.equals("navigation-admit")){
   WebView.Eval admit=preflight(activity);start(admit);Handler.advance(100);WebView.Eval pending=latest(page);
   page.client.onPageStarted(page,page.url,null);int events=WebView.events.size();
   pending.callback.onReceiveValue(json(new JSONObject().put("serial",BackgroundProbe.serial(admit)).put("phase","admit").put("ok",true)));
   check(WebView.events.size()==events&&!allowed("/api/session-send","POST"),"Prior navigation admission activated new document");return;
  }
  if(scenario.equals("navigation-suspend-deadline")){
   BackgroundProbe.pause(activity);Handler.advance(100);page.client.onPageStarted(page,page.url,null);Handler.advance(399);check(BackgroundProbe.count("pauseTimers")==0,"Navigation paused before original deadline");Handler.advance(1);check(BackgroundProbe.count("pauseTimers")==1,"Navigation canceled original bounded timer pause");return;
  }
  if(scenario.equals("old-client-navigation")){
   active(activity);page.client.onRenderProcessGone(page,new RenderProcessGoneDetail(){public boolean didCrash(){return true;}public int rendererPriorityAtExit(){return 0;}});
   for(android.view.View view:BackgroundProbe.flatten(activity.getWindow().getDecorView()))if(view instanceof android.widget.Button&&"Повторить".contentEquals(((android.widget.Button)view).getText()))view.performClick();
   long until=System.nanoTime()+2_000_000_000L;while(WebView.instances.size()<2&&System.nanoTime()<until){Handler.runPosted();Thread.sleep(2);}
   check(WebView.instances.size()==2,"Renderer replacement prerequisite");WebView replacement=WebView.instances.get(1);
   replacement.client.onPageFinished(replacement,replacement.url);WebView.Eval current=latest(replacement);
   page.client.onPageStarted(page,page.url,null);
   current.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(current)));
   check(replacement.client.shouldInterceptRequest(replacement,BackgroundProbe.request("/api/session","GET"))==null,"Old WebView navigation canceled current replacement preflight/admission");return;
  }
  if(scenario.equals("page-401-explicit-retry")){
   WebView.Eval admit=preflight(activity);start(admit);Handler.advance(100);WebView.Eval pending=latest(page);int calls=AuthHttp.calls;
   pending.callback.onReceiveValue(json(new JSONObject().put("serial",BackgroundProbe.serial(admit)).put("phase","admit").put("ok",false)));
   WebView.Eval cancel=latest(page);check(cancel.script.contains("aiControlAndroidSuspend")&&BackgroundProbe.serial(cancel)>BackgroundProbe.serial(admit),"Page admission failure did not close/cancel");
   check(!allowed("/api/session-send","POST")&&AuthHttp.calls==calls,"Page admission failure activated or auto-reauthenticated");
   cancel.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(cancel)));waitRetry(activity);retry(activity).performClick();waitCalls(calls+1);
   check(!allowed("/api/session-send","POST"),"Explicit native retry bypassed fresh page preflight");return;
  }
  if(scenario.equals("bootstrap-stop-finish")){
   int loads=BackgroundProbe.count("load");BackgroundProbe.pause(activity);Handler.advance(500);page.client.onPageFinished(page,page.url);
   activity.onStop();activity.onStart();BackgroundProbe.lifecycle(activity,"onResume");
   long until=System.nanoTime()+2_000_000_000L;while(BackgroundProbe.count("load")==loads&&System.nanoTime()<until){Handler.runPosted();Thread.sleep(2);}
   check(BackgroundProbe.count("load")==loads+1&&page.evals.isEmpty(),"Canceled unfinished-shell finish was mistaken for loaded protocol page");return;
  }
  if(scenario.equals("bootstrap-error")||scenario.equals("blocked-navigation-finish")){
   if(scenario.equals("page-401-explicit-retry")){
   WebView.Eval admit=preflight(activity);start(admit);Handler.advance(100);WebView.Eval pending=latest(page);int calls=AuthHttp.calls;
   pending.callback.onReceiveValue(json(new JSONObject().put("serial",BackgroundProbe.serial(admit)).put("phase","admit").put("ok",false)));
   WebView.Eval cancel=latest(page);check(cancel.script.contains("aiControlAndroidSuspend")&&BackgroundProbe.serial(cancel)>BackgroundProbe.serial(admit),"Page admission failure did not close/cancel");
   check(!allowed("/api/session-send","POST")&&AuthHttp.calls==calls,"Page admission failure activated or auto-reauthenticated");
   cancel.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(cancel)));waitRetry(activity);retry(activity).performClick();waitCalls(calls+1);
   check(!allowed("/api/session-send","POST"),"Explicit native retry bypassed fresh page preflight");return;
  }
  if(scenario.equals("bootstrap-stop-finish")){
   int loads=BackgroundProbe.count("load");BackgroundProbe.pause(activity);Handler.advance(500);page.client.onPageFinished(page,page.url);
   activity.onStop();activity.onStart();BackgroundProbe.lifecycle(activity,"onResume");
   long until=System.nanoTime()+2_000_000_000L;while(BackgroundProbe.count("load")==loads&&System.nanoTime()<until){Handler.runPosted();Thread.sleep(2);}
   check(BackgroundProbe.count("load")==loads+1&&page.evals.isEmpty(),"Canceled unfinished-shell finish was mistaken for loaded protocol page");return;
  }
  if(scenario.equals("bootstrap-error")){
    page.client.onReceivedHttpError(page,BackgroundProbe.request("/","GET"),new WebResourceResponse("text/plain","UTF-8",503,"Fixture",java.util.Collections.emptyMap(),new java.io.ByteArrayInputStream(new byte[0])));
    if(!page.evals.isEmpty())latest(page).callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(latest(page))));else Handler.advance(500);
    page.client.onPageFinished(page,page.url);
   }else{page.client.onPageStarted(page,"https://foreign.invalid/",null);page.client.onPageFinished(page,"https://foreign.invalid/");}
   waitRetry(activity);int loads=BackgroundProbe.count("load");retry(activity).performClick();
   long until=System.nanoTime()+2_000_000_000L;while(BackgroundProbe.count("load")==loads&&System.nanoTime()<until){Handler.runPosted();Thread.sleep(2);}
   check(BackgroundProbe.count("load")==loads+1,"Failed/blocked bootstrap finish prevented fresh initial shell retry");return;
  }
  if(scenario.equals("unsupported-cancel-ack")||scenario.equals("renderer-clears-latch")){
   WebView.Eval admit=preflight(activity);admit.callback.onReceiveValue(json(new JSONObject().put("unsupported",true)));
   WebView.Eval cancel=latest(page);cancel.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(cancel)));
   if(scenario.equals("unsupported-cancel-ack")){check(retry(activity)==null,"Unsupported state offered no-op retry");return;}
   int calls=AuthHttp.calls;page.client.onRenderProcessGone(page,new RenderProcessGoneDetail(){public boolean didCrash(){return true;}public int rendererPriorityAtExit(){return 0;}});
   waitRetry(activity);retry(activity).performClick();waitCalls(calls+1);return;
  }
  if(scenario.equals("offline-paused")){
   active(activity);BackgroundProbe.pause(activity);WebView.Eval stop=latest(page);stop.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(stop)));
   int evaluations=page.evals.size();AuthHttp.status=503;activity.onStop();activity.onStart();BackgroundProbe.lifecycle(activity,"onResume");waitRetry(activity);
   check(page.evals.size()==evaluations,"Native offline return evaluated JavaScript while page was already suspended/paused");
   int calls=AuthHttp.calls;AuthHttp.status=200;retry(activity).performClick();waitCalls(calls+1);return;
  }
  active(activity);BackgroundProbe.pause(activity);WebView.Eval stop=latest(page);stop.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(stop)));
  CookieManager.hold=true;activity.onStop();activity.onStart();BackgroundProbe.lifecycle(activity,"onResume");waitCookie();
  if(scenario.equals("cookie-background"))BackgroundProbe.pause(activity);
  else if(scenario.equals("cookie-navigation"))page.client.onPageStarted(page,page.url,null);
  else throw new AssertionError("Unknown author scenario");
  int events=WebView.events.size();CookieManager.pending.onReceiveValue(true);Handler.runPosted();
  check(WebView.events.size()==events&&page.getSettings().blocked,"Stale CookieManager callback resumed/unblocked page");
 }
}
